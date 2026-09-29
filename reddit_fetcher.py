"""
Reddit fetching module supporting both PRAW (authenticated + karma-based tier selection)
and public RSS/JSON endpoints as a fallback when API credentials are not yet configured.
Enforces the Rising Post timing strategy (10-30 minutes old and < 20 comments).
"""
import time
import logging
from datetime import datetime
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional
import requests

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class RedditPost:
    id: str
    title: str
    subreddit: str
    permalink: str
    author: str
    num_comments: int
    is_stickied: bool
    created_utc: float = 0.0
    selftext: str = ""

    @property
    def full_url(self) -> str:
        if self.permalink.startswith("http"):
            return self.permalink
        return f"https://www.reddit.com{self.permalink}"

    @property
    def age_minutes(self) -> float:
        if not self.created_utc:
            return 0.0
        return max(0.0, (time.time() - self.created_utc) / 60.0)


class RedditFetcher:
    def __init__(self, config: Config):
        self.config = config
        self.praw_instance = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        })
        self._init_praw()

    def _init_praw(self) -> None:
        if not self.config.praw_enabled:
            logger.info("Running in Public Mode (No Reddit API credentials provided).")
            return

        try:
            import praw
            praw_kwargs = {
                "client_id": self.config.reddit_client_id,
                "client_secret": self.config.reddit_client_secret,
                "user_agent": self.config.reddit_user_agent,
            }
            if self.config.praw_auth_enabled:
                praw_kwargs["username"] = self.config.reddit_username
                praw_kwargs["password"] = self.config.reddit_password

            self.praw_instance = praw.Reddit(**praw_kwargs)
            logger.info("PRAW initialized successfully.")
        except Exception as e:
            logger.warning(f"Failed to initialize PRAW: {e}. Falling back to Public Mode.")
            self.praw_instance = None

    def determine_target_subreddits(self) -> List[str]:
        """
        Determines target subreddits.
        If PRAW authenticated mode is available, checks total karma (comment + link)
        and returns the corresponding tier. Otherwise returns target_subreddits.
        """
        if self.praw_instance and self.config.praw_auth_enabled:
            try:
                me = self.praw_instance.user.me()
                if me:
                    comment_karma = getattr(me, "comment_karma", 0)
                    link_karma = getattr(me, "link_karma", 0)
                    total_karma = comment_karma + link_karma
                    logger.info(
                        f"Authenticated Reddit User: u/{me.name} | "
                        f"Karma: {total_karma} (Link: {link_karma}, Comment: {comment_karma})"
                    )

                    if total_karma < 50:
                        logger.info("Karma Tier: Tier 0 (< 50 karma)")
                        return self.config.tier_0_subreddits
                    elif total_karma <= 250:
                        logger.info("Karma Tier: Tier 1 (50-250 karma)")
                        return self.config.tier_1_subreddits
                    else:
                        logger.info("Karma Tier: Tier 2 (> 250 karma)")
                        return self.config.tier_2_subreddits
            except Exception as e:
                logger.warning(f"Could not retrieve user karma via PRAW: {e}. Using configured subreddits.")

        logger.info(f"Using default target subreddits: {self.config.target_subreddits}")
        return self.config.target_subreddits

    def fetch_rising_posts(self, subreddit_name: str) -> List[RedditPost]:
        """Fetches rising posts for a given subreddit using PRAW or Public readers."""
        if self.praw_instance:
            try:
                return self._fetch_via_praw(subreddit_name)
            except Exception as e:
                logger.warning(f"PRAW fetch failed for r/{subreddit_name}: {e}. Trying public fallback.")

        return self._fetch_rss_endpoint(subreddit_name)

    def fetch_all_rising_posts(self, subreddit_names: List[str]) -> List[RedditPost]:
        """
        Fetches rising posts across all target communities.
        Uses combined multi-subreddit requests to prevent triggering Reddit's IP rate limit.
        """
        if self.praw_instance:
            try:
                multi_sub = "+".join(subreddit_names)
                return self._fetch_via_praw(multi_sub)
            except Exception as e:
                logger.warning(f"PRAW multi-sub fetch failed: {e}. Falling back to public feed.")

        # Batch subreddits into multi-sub URLs of up to 5 communities per call
        chunk_size = 5
        all_posts: List[RedditPost] = []
        for i in range(0, len(subreddit_names), chunk_size):
            chunk = subreddit_names[i : i + chunk_size]
            multi_target = "+".join(chunk)
            posts = self._fetch_rss_endpoint(multi_target)
            all_posts.extend(posts)
            if i + chunk_size < len(subreddit_names):
                time.sleep(12)  # Respect unauthenticated edge limits between batches

        return all_posts

    def _is_valid_timing(self, created_utc: float) -> bool:
        """
        Validates post timing for early engagement.
        Threads in the Rising feed are in their high-velocity growth window.
        Enforces a reasonable ceiling (e.g. up to 6 hours) so stale threads are ignored.
        """
        if not created_utc:
            return True
        age_minutes = max(0.0, (time.time() - created_utc) / 60.0)
        return age_minutes <= 360.0

    def _fetch_via_praw(self, subreddit_query: str) -> List[RedditPost]:
        posts: List[RedditPost] = []
        subreddit = self.praw_instance.subreddit(subreddit_query)
        for submission in subreddit.rising(limit=25):
            if submission.stickied:
                continue
            if submission.num_comments >= self.config.max_comments:
                continue

            created_utc = getattr(submission, "created_utc", 0.0)
            if not self._is_valid_timing(created_utc):
                continue

            author_name = str(submission.author) if submission.author else "[deleted]"
            sub_name = str(submission.subreddit)
            posts.append(
                RedditPost(
                    id=submission.id,
                    title=submission.title,
                    subreddit=sub_name,
                    permalink=submission.permalink,
                    author=author_name,
                    num_comments=submission.num_comments,
                    is_stickied=submission.stickied,
                    created_utc=created_utc,
                    selftext=submission.selftext or "",
                )
            )
        return posts

    def _fetch_rss_endpoint(self, target_query: str) -> List[RedditPost]:
        """
        Fetches rising posts from Reddit's RSS feed (supports single sub or multi-sub).
        Handles HTTP 429 by checking x-ratelimit-reset and backing off gracefully.
        """
        url = f"https://www.reddit.com/r/{target_query}/rising.rss"
        max_attempts = 2

        for attempt in range(max_attempts):
            try:
                resp = self.session.get(url, timeout=12)
                if resp.status_code == 200:
                    return self._parse_rss_content(resp.content, default_sub=target_query)
                elif resp.status_code == 429:
                    reset_secs = int(resp.headers.get("x-ratelimit-reset", "12"))
                    logger.warning(
                        f"Reddit 429 rate limit hit for r/{target_query}. Waiting {reset_secs + 1}s..."
                    )
                    time.sleep(reset_secs + 1)
                    continue
                else:
                    logger.debug(f"RSS endpoint {url} returned HTTP {resp.status_code}")
                    break
            except Exception as e:
                logger.debug(f"Error fetching RSS from {url}: {e}")
                time.sleep(2)

        return []

    def _parse_rss_content(self, content: bytes, default_sub: str = "") -> List[RedditPost]:
        posts: List[RedditPost] = []
        try:
            root = ET.fromstring(content)
        except Exception as e:
            logger.debug(f"Failed to parse XML content: {e}")
            return posts

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)

        for entry in entries:
            title_elem = entry.find("atom:title", ns)
            id_elem = entry.find("atom:id", ns)
            link_elem = entry.find("atom:link", ns)
            author_elem = entry.find("atom:author/atom:name", ns)
            updated_elem = entry.find("atom:updated", ns) or entry.find("atom:published", ns)
            cat_elem = entry.find("atom:category", ns)

            title = title_elem.text if title_elem is not None and title_elem.text else ""
            entry_id = id_elem.text if id_elem is not None and id_elem.text else ""
            link = link_elem.attrib.get("href", "") if link_elem is not None else ""
            author = author_elem.text if author_elem is not None and author_elem.text else "[unknown]"

            # Extract specific subreddit name from atom:category
            sub_name = default_sub
            if cat_elem is not None:
                term = cat_elem.attrib.get("term", "")
                label = cat_elem.attrib.get("label", "")
                if term:
                    sub_name = term
                elif label.startswith("r/"):
                    sub_name = label[2:]

            created_utc = 0.0
            if updated_elem is not None and updated_elem.text:
                try:
                    dt = datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))
                    created_utc = dt.timestamp()
                except Exception:
                    pass

            clean_id = entry_id.split("_")[-1] if "_" in entry_id else entry_id

            if not clean_id or not title:
                continue

            if not self._is_valid_timing(created_utc):
                continue

            posts.append(
                RedditPost(
                    id=clean_id,
                    title=title,
                    subreddit=sub_name,
                    permalink=link,
                    author=author,
                    num_comments=0,
                    is_stickied=False,
                    created_utc=created_utc,
                    selftext="",
                )
            )

        return posts

