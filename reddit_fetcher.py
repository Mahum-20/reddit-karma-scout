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
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            )
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

        return self._fetch_via_public(subreddit_name)

    def _is_valid_timing(self, created_utc: float) -> bool:
        """Enforces the Rising Post timing strategy: 10 to 30 minutes old."""
        if not created_utc:
            # If timestamp missing, allow through to avoid false drops
            return True
        age_minutes = (time.time() - created_utc) / 60.0
        return self.config.min_post_age_minutes <= age_minutes <= self.config.max_post_age_minutes

    def _fetch_via_praw(self, subreddit_name: str) -> List[RedditPost]:
        posts: List[RedditPost] = []
        subreddit = self.praw_instance.subreddit(subreddit_name)
        for submission in subreddit.rising(limit=25):
            if submission.stickied:
                continue
            if submission.num_comments >= self.config.max_comments:
                continue

            created_utc = getattr(submission, "created_utc", 0.0)
            if not self._is_valid_timing(created_utc):
                age_m = (time.time() - created_utc) / 60.0 if created_utc else 0
                logger.debug(
                    f"Skipping post {submission.id} (age: {age_m:.1f}m - outside {self.config.min_post_age_minutes}-{self.config.max_post_age_minutes}m window)"
                )
                continue

            author_name = str(submission.author) if submission.author else "[deleted]"
            posts.append(
                RedditPost(
                    id=submission.id,
                    title=submission.title,
                    subreddit=subreddit_name,
                    permalink=submission.permalink,
                    author=author_name,
                    num_comments=submission.num_comments,
                    is_stickied=submission.stickied,
                    created_utc=created_utc,
                    selftext=submission.selftext or "",
                )
            )
        return posts

    def _fetch_via_public(self, subreddit_name: str) -> List[RedditPost]:
        """Fetches rising posts via public JSON endpoint with RSS fallback."""
        json_url = f"https://www.reddit.com/r/{subreddit_name}/rising.json?limit=25"
        try:
            resp = self.session.get(json_url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                posts: List[RedditPost] = []
                for item in children:
                    d = item.get("data", {})
                    stickied = d.get("stickied", False)
                    num_comments = d.get("num_comments", 0)

                    if stickied or num_comments >= self.config.max_comments:
                        continue

                    post_id = d.get("id")
                    if not post_id:
                        continue

                    created_utc = float(d.get("created_utc", 0.0))
                    if not self._is_valid_timing(created_utc):
                        age_m = (time.time() - created_utc) / 60.0 if created_utc else 0
                        logger.debug(
                            f"Skipping post {post_id} (age: {age_m:.1f}m - outside {self.config.min_post_age_minutes}-{self.config.max_post_age_minutes}m window)"
                        )
                        continue

                    posts.append(
                        RedditPost(
                            id=post_id,
                            title=d.get("title", ""),
                            subreddit=subreddit_name,
                            permalink=d.get("permalink", f"/r/{subreddit_name}/comments/{post_id}"),
                            author=d.get("author", "[unknown]"),
                            num_comments=num_comments,
                            is_stickied=stickied,
                            created_utc=created_utc,
                            selftext=d.get("selftext", ""),
                        )
                    )
                if posts:
                    return posts
            elif resp.status_code == 429:
                logger.warning(f"Reddit rate-limited public JSON request (429) for r/{subreddit_name}.")
            else:
                logger.debug(f"Public JSON returned HTTP {resp.status_code} for r/{subreddit_name}.")
        except Exception as e:
            logger.debug(f"Public JSON error for r/{subreddit_name}: {e}")

        # 2. Try RSS feed fallback
        return self._fetch_via_rss(subreddit_name)

    def _fetch_via_rss(self, subreddit_name: str) -> List[RedditPost]:
        rss_url = f"https://www.reddit.com/r/{subreddit_name}/rising/.rss"
        posts: List[RedditPost] = []
        try:
            resp = self.session.get(rss_url, timeout=10)
            if resp.status_code != 200:
                logger.debug(f"Public RSS returned HTTP {resp.status_code} for r/{subreddit_name}.")
                return []

            root = ET.fromstring(resp.content)
            namespace = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", namespace)

            for entry in entries:
                title_elem = entry.find("atom:title", namespace)
                id_elem = entry.find("atom:id", namespace)
                link_elem = entry.find("atom:link", namespace)
                author_elem = entry.find("atom:author/atom:name", namespace)
                updated_elem = entry.find("atom:updated", namespace) or entry.find("atom:published", namespace)

                title = title_elem.text if title_elem is not None else ""
                entry_id = id_elem.text if id_elem is not None else ""
                link = link_elem.attrib.get("href", "") if link_elem is not None else ""
                author = author_elem.text if author_elem is not None else "[unknown]"

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
                        subreddit=subreddit_name,
                        permalink=link,
                        author=author,
                        num_comments=0,
                        is_stickied=False,
                        created_utc=created_utc,
                        selftext="",
                    )
                )
        except Exception as e:
            logger.debug(f"Public RSS error for r/{subreddit_name}: {e}")

        return posts
