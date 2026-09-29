"""
Main execution script for Reddit Karma Scout.
Monitors rising posts on Reddit, drafts casual comments using Gemini AI,
and alerts Discord via webhooks. Runs continuously on Render (as a Worker or Web Service).
"""
import os
import time
import signal
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

from config import load_config
from storage import PostStorage
from reddit_fetcher import RedditFetcher
from ai_drafter import AIDrafter
from discord_notifier import DiscordNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("RedditKarmaScout")

# Global running flag for graceful shutdowns
RUNNING = True


def handle_shutdown(signum, frame):
    global RUNNING
    logger.info(f"Received signal {signum}. Shutting down gracefully...")
    RUNNING = False


# Lightweight HTTP server for Render Web Service compatibility
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Reddit Karma Scout is active.\n")

    def log_message(self, format, *args):
        # Silence HTTP access logs
        return


def start_health_server_if_needed():
    """If PORT is defined in environment, starts a lightweight health check HTTP server in a thread."""
    port_str = os.getenv("PORT")
    if not port_str:
        return

    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Render Web Service port detected. Healthcheck server running on port {port}.")
    except Exception as e:
        logger.warning(f"Failed to start healthcheck server on port {port_str}: {e}")


def start_keep_alive_pinger_if_needed():
    """
    Render Free Web Services spin down after 15 minutes without incoming HTTP traffic.
    This thread periodically pings the public Render URL to keep the container awake.
    """
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("KEEP_ALIVE_URL")
    if not url:
        logger.info("No RENDER_EXTERNAL_URL or KEEP_ALIVE_URL found. Self-pinger disabled (external monitor recommended).")
        return

    def pinger_loop():
        logger.info(f"Keep-alive self-pinger active for: {url} (Interval: 10 minutes)")
        # Wait 90 seconds after boot before sending first ping
        time.sleep(90)
        while RUNNING:
            try:
                resp = requests.get(url, timeout=15)
                logger.info(f"Keep-alive ping sent to {url} (HTTP {resp.status_code})")
            except Exception as e:
                logger.debug(f"Keep-alive ping error: {e}")

            # Sleep 10 minutes (600 seconds) - safely before Render's 15m timeout
            elapsed = 0
            while RUNNING and elapsed < 600:
                time.sleep(5)
                elapsed += 5

    thread = threading.Thread(target=pinger_loop, daemon=True)
    thread.start()


def main():
    global RUNNING

    # Attach signal handlers for Render and Docker
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    logger.info("=========================================")
    logger.info("   Starting Reddit Karma Scout v1.0      ")
    logger.info("=========================================")

    # Start healthcheck server if running on Render Web Service
    start_health_server_if_needed()

    # Start keep-alive self-pinger to prevent Render spin-down
    start_keep_alive_pinger_if_needed()

    config = load_config()
    storage = PostStorage(config.database_path)
    fetcher = RedditFetcher(config)
    drafter = AIDrafter(config)
    notifier = DiscordNotifier(config)

    logger.info(f"Scan Interval: {config.scan_interval_seconds} seconds")
    logger.info(f"Comment Threshold: < {config.max_comments} comments")
    logger.info(f"Post Timing Window: {config.min_post_age_minutes} to {config.max_post_age_minutes} minutes old")
    logger.info(f"Hourly Reply Limit: {config.max_replies_per_hour} replies/hour max")
    logger.info(f"Mode: {'PRAW (API)' if config.praw_enabled else 'Public RSS/JSON'}")

    # Send startup confirmation to Discord
    notifier.send_startup_ping(
        subreddits=config.target_subreddits,
        min_age=config.min_post_age_minutes,
        max_age=config.max_post_age_minutes,
        max_hourly=config.max_replies_per_hour,
    )

    iteration = 0
    while RUNNING:
        iteration += 1
        current_hourly_count = storage.get_hourly_reply_count()
        logger.info(f"--- Starting Scan Cycle #{iteration} (Replies in past hour: {current_hourly_count}/{config.max_replies_per_hour}) ---")

        try:
            # Determine target subreddits (PRAW karma tiers or public defaults)
            target_subreddits = fetcher.determine_target_subreddits()
            logger.info(f"Target Subreddits ({len(target_subreddits)}): {', '.join(target_subreddits)}")

            # 1. Deliver 1 ready-to-post submission concept to Discord
            sub_for_idea = target_subreddits[(iteration - 1) % len(target_subreddits)]
            logger.info(f"Generating ready-to-post submission concept for r/{sub_for_idea}...")
            post_idea = drafter.generate_original_post_idea(sub_for_idea)
            if post_idea:
                notifier.send_post_idea(sub_for_idea, post_idea)
                logger.info(f"Delivered ready-to-post idea for r/{sub_for_idea} to Discord.")
                time.sleep(5.0)

            # 2. Check comment quota and scan rising threads across target communities
            if not storage.can_generate_reply(config.max_replies_per_hour):
                logger.warning(
                    f"Hourly reply quota reached ({config.max_replies_per_hour}/{config.max_replies_per_hour}). "
                    f"Pausing comment alerts until the rolling hour resets."
                )
            else:
                logger.info("Scanning rising threads across monitored communities...")
                posts = fetcher.fetch_all_rising_posts(target_subreddits)
                logger.info(f"Retrieved {len(posts)} candidate rising threads.")

                new_posts_found = 0
                for post in posts:
                    if not RUNNING:
                        break

                    if not storage.can_generate_reply(config.max_replies_per_hour):
                        logger.warning("Hourly quota reached during cycle. Stopping further generation.")
                        break

                    if storage.is_processed(post.id):
                        continue

                    new_posts_found += 1
                    age_str = f"{post.age_minutes:.1f}m old" if post.created_utc else "Rising"
                    logger.info(
                        f"Found qualified rising thread in r/{post.subreddit}: "
                        f"'{post.title[:50]}...' ({age_str})"
                    )

                    # Generate high-upvote AI comment draft
                    draft = drafter.draft_comment(
                        subreddit=post.subreddit,
                        post_title=post.title,
                        selftext=post.selftext,
                    )

                    if not draft:
                        logger.warning(f"Skipping alert for post {post.id} because custom draft generation was throttled.")
                        continue

                    # Record reply to enforce hourly quota
                    storage.record_reply(post.id)
                    current_count = storage.get_hourly_reply_count()

                    # Send Discord webhook alert with timing and quota info
                    notifier.send_alert(
                        post=post,
                        draft_comment=draft,
                        hourly_count=current_count,
                        max_hourly=config.max_replies_per_hour,
                    )

                    # Persist as processed so we never alert twice
                    storage.mark_processed(
                        post_id=post.id,
                        subreddit=post.subreddit,
                        title=post.title,
                    )

                    # Pacing delay between posts to respect Google Gemini free tier rate limits (5 RPM)
                    time.sleep(6.0)

                    # Cap at 2 comment alerts per cycle to prevent rate-limit flooding and keep quality high
                    if new_posts_found >= 2:
                        break

                logger.info(f"Cycle #{iteration} complete. Flagged {new_posts_found} new comment opportunities.")

            # Periodic cleanup of old database records
            if iteration % 20 == 0:
                storage.cleanup_old_records()

        except Exception as e:
            logger.error(f"Unexpected error during scan cycle: {e}", exc_info=True)

        # Configurable sleep interval with interruption check
        logger.info(f"Sleeping for {config.scan_interval_seconds}s until next scan cycle...")
        sleep_elapsed = 0
        while RUNNING and sleep_elapsed < config.scan_interval_seconds:
            time.sleep(1)
            sleep_elapsed += 1

    logger.info("Reddit Karma Scout terminated cleanly.")


if __name__ == "__main__":
    main()
