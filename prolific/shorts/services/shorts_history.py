"""SQLite history tracking for shorts pipeline."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class ShortsHistoryService:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.shorts_history_db_path

    async def _ensure_table(self, db: aiosqlite.Connection) -> None:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shorts (
                id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                hook TEXT DEFAULT '',
                script_text TEXT DEFAULT '',
                word_count INTEGER DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                youtube_video_id TEXT,
                youtube_url TEXT,
                video_path TEXT,
                status TEXT DEFAULT 'planned',
                cost_usd REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                published_at TEXT
            )
        """)
        await db.commit()

    async def get_past_topics(self, hours: int = 48) -> list[str]:
        """Get topics covered in the last N hours to avoid repeats."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            cursor = await db.execute(
                "SELECT topic FROM shorts WHERE created_at > ? ORDER BY created_at DESC",
                (cutoff,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def record_short(
        self,
        short_id: str,
        topic: str,
        hook: str = "",
        script_text: str = "",
        word_count: int = 0,
        duration_seconds: float = 0.0,
        youtube_video_id: str | None = None,
        youtube_url: str | None = None,
        video_path: str | None = None,
        status: str = "published",
        cost_usd: float = 0.0,
    ) -> None:
        """Record a generated short in the history database."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """INSERT OR REPLACE INTO shorts
                   (id, topic, hook, script_text, word_count, duration_seconds,
                    youtube_video_id, youtube_url, video_path, status, cost_usd,
                    created_at, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    short_id, topic, hook, script_text, word_count, duration_seconds,
                    youtube_video_id, youtube_url, video_path, status, cost_usd,
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat() if youtube_url else None,
                ),
            )
            await db.commit()
        logger.info(f"Recorded short: {topic} ({status})")

    async def get_history(self, limit: int = 50) -> list[dict]:
        """Get recent shorts history."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM shorts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


_history_service: ShortsHistoryService | None = None


def get_shorts_history_service() -> ShortsHistoryService:
    global _history_service
    if _history_service is None:
        _history_service = ShortsHistoryService()
    return _history_service
