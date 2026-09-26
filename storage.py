"""
Persistent storage module using SQLite and in-memory set cache
to prevent duplicate processing and duplicate alerts, as well as enforcing
hourly reply rate limits.
"""
import sqlite3
import logging
from typing import Set

logger = logging.getLogger(__name__)


class PostStorage:
    def __init__(self, db_path: str = "processed_posts.db"):
        self.db_path = db_path
        self._cache: Set[str] = set()
        self._init_db()
        self._load_cache()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS processed_posts (
                        id TEXT PRIMARY KEY,
                        subreddit TEXT,
                        title TEXT,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_processed_at ON processed_posts(processed_at)")

                # Table tracking generated replies for hourly rate-limiting
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS generated_replies (
                        post_id TEXT PRIMARY KEY,
                        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_gen_at ON generated_replies(generated_at)")
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing SQLite database at {self.db_path}: {e}")

    def _load_cache(self) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM processed_posts")
                rows = cursor.fetchall()
                self._cache = {row[0] for row in rows}
            logger.info(f"Loaded {len(self._cache)} previously processed posts from cache.")
        except Exception as e:
            logger.error(f"Error loading post cache: {e}")
            self._cache = set()

    def is_processed(self, post_id: str) -> bool:
        """Fast O(1) in-memory check."""
        return post_id in self._cache

    def mark_processed(self, post_id: str, subreddit: str, title: str) -> None:
        """Adds post ID to in-memory cache and persists to SQLite."""
        self._cache.add(post_id)
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO processed_posts (id, subreddit, title) VALUES (?, ?, ?)",
                    (post_id, subreddit, title)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist post {post_id} to database: {e}")

    def get_hourly_reply_count(self) -> int:
        """Counts how many replies were generated in the rolling past 60 minutes."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT COUNT(*) FROM generated_replies 
                    WHERE generated_at >= datetime('now', '-1 hour')
                """)
                row = cursor.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Error getting hourly reply count: {e}")
            return 0

    def can_generate_reply(self, max_per_hour: int = 10) -> bool:
        """Checks if we are within the hourly reply generation quota."""
        count = self.get_hourly_reply_count()
        return count < max_per_hour

    def record_reply(self, post_id: str) -> None:
        """Records a reply generation event to enforce hourly rate limit."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR IGNORE INTO generated_replies (post_id) VALUES (?)",
                    (post_id,)
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Error recording generated reply for {post_id}: {e}")

    def cleanup_old_records(self, max_records: int = 10000) -> None:
        """Prunes old records from tables."""
        if len(self._cache) > max_records:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        DELETE FROM processed_posts
                        WHERE id NOT IN (
                            SELECT id FROM processed_posts ORDER BY processed_at DESC LIMIT ?
                        )
                    """, (max_records,))
                    cursor.execute("""
                        DELETE FROM generated_replies 
                        WHERE generated_at < datetime('now', '-7 days')
                    """)
                    conn.commit()
                self._load_cache()
                logger.info(f"Pruned database to {len(self._cache)} most recent records.")
            except Exception as e:
                logger.error(f"Error pruning database: {e}")
