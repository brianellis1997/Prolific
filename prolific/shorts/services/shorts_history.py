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
                published_at TEXT,
                selection_rationale TEXT DEFAULT ''
            )
        """)
        try:
            await db.execute("ALTER TABLE shorts ADD COLUMN selection_rationale TEXT DEFAULT ''")
        except Exception:
            pass
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

    async def get_past_topics_with_keywords(self, hours: int = 720) -> str:
        """Get past topics with extracted keywords for fuzzy duplicate avoidance.

        Returns a formatted string for the LLM prompt that includes both the
        full topic AND extracted key subjects so rephrased duplicates get caught.
        """
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()

        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            cursor = await db.execute(
                "SELECT topic FROM shorts WHERE created_at > ? ORDER BY created_at DESC",
                (cutoff,),
            )
            rows = await cursor.fetchall()

        if not rows:
            return "(none yet)"

        topics = [row[0] for row in rows]
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
            "to", "for", "of", "and", "or", "but", "not", "its", "it", "this",
            "that", "your", "you", "can", "will", "how", "why", "what", "than",
            "from", "with", "has", "had", "have", "been", "do", "does", "did",
            "just", "more", "most", "really", "actually", "still", "even",
            "every", "after", "before", "about", "when", "if", "so", "be",
        }

        all_subjects = set()
        lines = []
        for topic in topics:
            words = [w.lower().strip(".,!?'\"") for w in topic.split()]
            keywords = [w for w in words if len(w) > 3 and w not in stop_words]
            all_subjects.update(keywords)
            lines.append(f"- {topic}")

        lines.append(f"\nKEY SUBJECTS ALREADY COVERED (do NOT reuse in ANY form):")
        lines.append(", ".join(sorted(all_subjects)))

        return "\n".join(lines)

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
        selection_rationale: str = "",
    ) -> None:
        """Record a generated short in the history database."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """INSERT OR REPLACE INTO shorts
                   (id, topic, hook, script_text, word_count, duration_seconds,
                    youtube_video_id, youtube_url, video_path, status, cost_usd,
                    created_at, published_at, selection_rationale)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    short_id, topic, hook, script_text, word_count, duration_seconds,
                    youtube_video_id, youtube_url, video_path, status, cost_usd,
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat() if youtube_url else None,
                    selection_rationale,
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
