"""
Discord Webhook Notifier module.
Formats and sends rich Discord embeds containing the post title, direct link,
timing metadata (post age), hourly quota status, and the AI draft styled
inside a code block for one-click copying.
"""
import time
import logging
from datetime import datetime, timezone
from typing import Optional
import requests

from config import Config
from reddit_fetcher import RedditPost

logger = logging.getLogger(__name__)


class DiscordNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.webhook_url = config.discord_webhook_url
        self.session = requests.Session()

    def send_startup_ping(self, subreddits: list, min_age: int, max_age: int, max_hourly: int) -> bool:
        """Sends an immediate startup confirmation embed to Discord."""
        if not self.webhook_url:
            return False
        subs_str = ", ".join([f"r/{s}" for s in subreddits[:5]])
        embed = {
            "title": "🟢 Reddit Karma Scout is Online!",
            "description": "Scout successfully initialized on Render and is actively monitoring Reddit rising feeds.",
            "color": 0x2ECC71,  # Green
            "fields": [
                {
                    "name": "Target Communities",
                    "value": f"`{subs_str}`",
                    "inline": False,
                },
                {
                    "name": "Timing Window",
                    "value": f"`{min_age} to {max_age}m old`",
                    "inline": True,
                },
                {
                    "name": "Hourly Quota",
                    "value": f"`Max {max_hourly}/hr`",
                    "inline": True,
                },
                {
                    "name": "Mode",
                    "value": "`PRAW API`" if self.config.praw_enabled else "`Public Feed`",
                    "inline": True,
                },
            ],
            "footer": {
                "text": "Status: Active • Alerts will arrive as matching threads qualify",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            r = self.session.post(self.webhook_url, json={"username": "Karma Scout", "embeds": [embed]}, timeout=10)
            return r.status_code in (200, 204)
        except Exception:
            return False

    def send_alert(
        self,
        post: RedditPost,
        draft_comment: str,
        hourly_count: int = 1,
        max_hourly: int = 10,
    ) -> bool:
        """
        Sends an alert embed to Discord Webhook with post timing,
        hourly quota status, and the suggested draft in a code block.
        """
        if not self.webhook_url:
            logger.info(
                f"[DISCORD WEBHOOK NOT CONFIGURED] Would have posted:\n"
                f"  Subreddit: r/{post.subreddit}\n"
                f"  Post: {post.title}\n"
                f"  URL: {post.full_url}\n"
                f"  Age: {post.age_minutes:.1f}m | Quota: {hourly_count}/{max_hourly}\n"
                f"  Draft: {draft_comment}\n"
            )
            return False

        # Discord title limit is 256 chars
        clean_title = post.title.strip()
        if len(clean_title) > 240:
            clean_title = clean_title[:237] + "..."

        age_display = f"{post.age_minutes:.0f}m ago" if post.created_utc else "Rising"

        embed = {
            "title": f"🚨 Rising Post in r/{post.subreddit} ({age_display})",
            "description": f"**[{clean_title}]({post.full_url})**\n\n**Suggested Reply (Copy Below):**\n```{draft_comment}```",
            "url": post.full_url,
            "color": 0xFF4500,  # Reddit Orangered
            "fields": [
                {
                    "name": "Subreddit",
                    "value": f"`r/{post.subreddit}`",
                    "inline": True,
                },
                {
                    "name": "Post Age",
                    "value": f"`{age_display}`",
                    "inline": True,
                },
                {
                    "name": "Comments",
                    "value": f"`{post.num_comments}`",
                    "inline": True,
                },
                {
                    "name": "Author",
                    "value": f"`u/{post.author}`",
                    "inline": True,
                },
                {
                    "name": "Hourly Quota",
                    "value": f"`{hourly_count}/{max_hourly}`",
                    "inline": True,
                },
            ],
            "footer": {
                "text": "Reddit Karma Scout • 10-30m Rising Strategy",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        payload = {
            "username": "Karma Scout",
            "avatar_url": "https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png",
            "embeds": [embed],
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(self.webhook_url, json=payload, timeout=10)
                if response.status_code in (200, 204):
                    logger.info(
                        f"Discord alert sent for post {post.id} (Age: {age_display}, Quota: {hourly_count}/{max_hourly})"
                    )
                    return True
                elif response.status_code == 429:
                    retry_after = response.json().get("retry_after", 2)
                    logger.warning(f"Discord rate limit hit. Waiting {retry_after}s...")
                    time.sleep(float(retry_after))
                else:
                    logger.error(
                        f"Discord webhook failed with HTTP {response.status_code}: {response.text}"
                    )
                    break
            except Exception as e:
                logger.error(f"Error posting to Discord webhook: {e}")
                time.sleep(1)

        return False

    def send_post_idea(self, subreddit: str, post_idea: dict) -> bool:
        """
        Sends a ready-to-submit post concept to Discord.
        Provides single-click copy blocks for Title and Body plus direct Reddit submit link.
        """
        if not self.webhook_url:
            logger.info(
                f"[DISCORD WEBHOOK NOT CONFIGURED] Post Idea for r/{subreddit}:\n"
                f"  Title: {post_idea.get('title')}\n"
                f"  Body: {post_idea.get('body')}\n"
                f"  Strategy: {post_idea.get('strategy')}\n"
            )
            return False

        title = post_idea.get("title", "").strip()
        body = post_idea.get("body", "").strip()
        strategy = post_idea.get("strategy", "High upvote discussion starter").strip()
        submit_url = f"https://www.reddit.com/r/{subreddit}/submit"

        fields = [
            {
                "name": "📌 Post Title (Click to Copy)",
                "value": f"```{title}```",
                "inline": False,
            }
        ]

        if body:
            fields.append({
                "name": "📝 Post Body (Click to Copy)",
                "value": f"```{body}```",
                "inline": False,
            })
        else:
            fields.append({
                "name": "📝 Post Body",
                "value": "*Title-only post (leave body empty on Reddit)*",
                "inline": False,
            })

        fields.append({
            "name": "🎯 Upvote Strategy",
            "value": f"*{strategy}*",
            "inline": False,
        })

        embed = {
            "title": f"💡 Ready-to-Post Concept for r/{subreddit}",
            "description": f"Submit this directly to **r/{subreddit}** to gain post karma & spark discussion.\n\n[➡️ **Click to Open Reddit Submit Page**]({submit_url})",
            "url": submit_url,
            "color": 0x9B59B6,  # Royal Purple
            "fields": fields,
            "footer": {
                "text": "Reddit Karma Scout • Original Post Generator",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        payload = {
            "username": "Karma Scout",
            "avatar_url": "https://www.redditstatic.com/desktop2x/img/favicon/android-icon-192x192.png",
            "embeds": [embed],
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.post(self.webhook_url, json=payload, timeout=10)
                if response.status_code in (200, 204):
                    logger.info(f"Discord post idea sent successfully for r/{subreddit}")
                    return True
                elif response.status_code == 429:
                    retry_after = response.json().get("retry_after", 2)
                    logger.warning(f"Discord rate limit hit. Waiting {retry_after}s...")
                    time.sleep(float(retry_after))
                else:
                    logger.error(
                        f"Discord webhook failed with HTTP {response.status_code}: {response.text}"
                    )
                    break
            except Exception as e:
                logger.error(f"Error posting post idea to Discord: {e}")
                time.sleep(1)

        return False
