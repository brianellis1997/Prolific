"""SQLite tracker for comment replies — prevents double-replying."""

import logging
from datetime import datetime, timedelta, UTC
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "./comment_replies.db"


class CommentTracker:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    async def _ensure_table(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS comment_replies (
                comment_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                author TEXT,
                comment_text TEXT,
                reply_text TEXT,
                replied_at TEXT NOT NULL
            )
        """)
        await db.commit()

    async def has_replied(self, comment_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            cursor = await db.execute(
                "SELECT 1 FROM comment_replies WHERE comment_id = ?",
                (comment_id,),
            )
            return await cursor.fetchone() is not None

    async def record_reply(
        self,
        comment_id: str,
        video_id: str,
        channel: str,
        author: str,
        comment_text: str,
        reply_text: str,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """INSERT OR IGNORE INTO comment_replies
                   (comment_id, video_id, channel, author, comment_text, reply_text, replied_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (comment_id, video_id, channel, author, comment_text, reply_text,
                 datetime.now(UTC).isoformat()),
            )
            await db.commit()

    async def get_recent_replies(self, hours: int = 24) -> list[dict]:
        cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM comment_replies WHERE replied_at > ? ORDER BY replied_at DESC",
                (cutoff,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


_tracker: CommentTracker | None = None


def get_comment_tracker() -> CommentTracker:
    global _tracker
    if _tracker is None:
        _tracker = CommentTracker()
    return _tracker
