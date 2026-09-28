"""
Configuration module for Reddit Karma Scout.
Loads settings from environment variables and sets up defaults.
"""
import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

# Load local .env if present
load_dotenv()


@dataclass
class Config:
    # Google Gemini Settings
    gemini_api_key: str
    gemini_model: str

    # Discord Webhook Settings
    discord_webhook_url: str

    # Reddit API / PRAW Settings (Optional - leave empty for Public Mode)
    reddit_client_id: Optional[str]
    reddit_client_secret: Optional[str]
    reddit_user_agent: str
    reddit_username: Optional[str]
    reddit_password: Optional[str]

    # Karma Tiers for PRAW mode
    tier_0_subreddits: List[str]
    tier_1_subreddits: List[str]
    tier_2_subreddits: List[str]

    # Target Subreddits for Public RSS/JSON mode (or manual override)
    target_subreddits: List[str]

    # Scanning filters & loop
    max_comments: int
    min_post_age_minutes: int
    max_post_age_minutes: int
    max_replies_per_hour: int
    scan_interval_seconds: int
    database_path: str

    @property
    def praw_enabled(self) -> bool:
        """Returns True if minimum credentials for PRAW are available."""
        return bool(self.reddit_client_id and self.reddit_client_secret)

    @property
    def praw_auth_enabled(self) -> bool:
        """Returns True if full Reddit user authentication (username + password) is provided."""
        return bool(self.praw_enabled and self.reddit_username and self.reddit_password)


def load_config() -> Config:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    reddit_client_id = os.getenv("REDDIT_CLIENT_ID", "").strip() or None
    reddit_client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip() or None
    reddit_user_agent = os.getenv("REDDIT_USER_AGENT", "RedditKarmaScout/1.0").strip()
    reddit_username = os.getenv("REDDIT_USERNAME", "").strip() or None
    reddit_password = os.getenv("REDDIT_PASSWORD", "").strip() or None

    # Default Karma Tiers as specified in requirements
    tier_0 = [
        "AskReddit", "NoStupidQuestions", "CasualConversation",
        "memes", "aww", "Showerthoughts", "explainlikeimfive"
    ]
    tier_1 = ["technology", "funny", "Showerthoughts", "explainlikeimfive", "todayilearned"]
    tier_2 = ["buildapc", "gaming", "popheads", "Discussion"]

    # Target subreddits override for public mode
    custom_subreddits = os.getenv("TARGET_SUBREDDITS", "").strip()
    if custom_subreddits:
        target_subreddits = [s.strip().replace("r/", "") for s in custom_subreddits.split(",") if s.strip()]
    else:
        target_subreddits = tier_0

    max_comments = int(os.getenv("POST_COMMENT_LIMIT", "20"))
    min_post_age_minutes = int(os.getenv("MIN_POST_AGE_MINUTES", "5"))
    max_post_age_minutes = int(os.getenv("MAX_POST_AGE_MINUTES", "45"))
    max_replies_per_hour = int(os.getenv("MAX_REPLIES_PER_HOUR", "10"))
    scan_interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "180"))
    db_path = os.getenv("DATABASE_PATH", "processed_posts.db").strip()

    return Config(
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        discord_webhook_url=discord_webhook_url,
        reddit_client_id=reddit_client_id,
        reddit_client_secret=reddit_client_secret,
        reddit_user_agent=reddit_user_agent,
        reddit_username=reddit_username,
        reddit_password=reddit_password,
        tier_0_subreddits=tier_0,
        tier_1_subreddits=tier_1,
        tier_2_subreddits=tier_2,
        target_subreddits=target_subreddits,
        max_comments=max_comments,
        min_post_age_minutes=min_post_age_minutes,
        max_post_age_minutes=max_post_age_minutes,
        max_replies_per_hour=max_replies_per_hour,
        scan_interval_seconds=scan_interval,
        database_path=db_path,
    )
