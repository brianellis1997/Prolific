"""SQLite history tracking for shorts pipeline."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
import numpy as np

from prolific.core.config import settings
from prolific.services.topic_dedup import (
    PastTopicEmbedding,
    blob_to_embedding,
    embedding_to_blob,
)

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
        try:
            await db.execute("ALTER TABLE shorts ADD COLUMN embedding BLOB")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE shorts ADD COLUMN embedding_model_version TEXT")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS used_stock_clips (
                video_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pexels',
                search_query TEXT NOT NULL,
                short_id TEXT,
                used_at TEXT NOT NULL,
                PRIMARY KEY (video_id, source)
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

    async def get_used_clip_ids(self, source: str = "pexels", hours: int = 720) -> set[str]:
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            cursor = await db.execute(
                "SELECT video_id FROM used_stock_clips WHERE source = ? AND used_at > ?",
                (source, cutoff),
            )
            rows = await cursor.fetchall()
            return {str(row[0]) for row in rows}

    async def record_clip_usage(
        self,
        video_id: str | int,
        source: str = "pexels",
        search_query: str = "",
        short_id: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """INSERT OR IGNORE INTO used_stock_clips
                   (video_id, source, search_query, short_id, used_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(video_id), source, search_query, short_id, datetime.utcnow().isoformat()),
            )
            await db.commit()

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

    async def get_past_topics_with_embeddings(self, limit: int = 200) -> list[PastTopicEmbedding]:
        """Pull past published shorts with cached embeddings for the dedup gate.

        Limit-based (not hours-based): the original 48h/720h windows aged topics
        out so fast that the same topic could come back within ~1 week. We need
        a much wider window for semantic dedup to work.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT id, youtube_video_id, topic, hook, selection_rationale,
                          published_at, embedding, embedding_model_version
                   FROM shorts
                   WHERE youtube_video_id IS NOT NULL AND youtube_video_id != ''
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            results: list[PastTopicEmbedding] = []
            for row in rows:
                pub_at: datetime | None = None
                if row["published_at"]:
                    try:
                        pub_at = datetime.fromisoformat(row["published_at"])
                    except Exception:
                        pub_at = None
                results.append(
                    PastTopicEmbedding(
                        video_id=row["youtube_video_id"] or row["id"],
                        topic=row["topic"],
                        title=row["topic"],
                        published_at=pub_at,
                        embedding=blob_to_embedding(row["embedding"]),
                        embedding_model_version=row["embedding_model_version"],
                    )
                )
            return results

    async def update_embedding(
        self, video_id: str, embedding: np.ndarray, model_version: str
    ) -> None:
        """Persist a cached embedding for a published short.

        `video_id` matches `youtube_video_id` (YouTube ID, not UUID).
        """
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            await db.execute(
                """UPDATE shorts
                   SET embedding = ?, embedding_model_version = ?
                   WHERE youtube_video_id = ? OR id = ?""",
                (embedding_to_blob(embedding), model_version, video_id, video_id),
            )
            await db.commit()

    async def get_short_by_id(self, video_id: str) -> dict | None:
        """Look up a short by `youtube_video_id` or internal UUID for Part 2 lookup."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._ensure_table(db)
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM shorts WHERE youtube_video_id = ? OR id = ? LIMIT 1",
                (video_id, video_id),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None


_history_service: ShortsHistoryService | None = None


def get_shorts_history_service() -> ShortsHistoryService:
    global _history_service
    if _history_service is None:
        _history_service = ShortsHistoryService()
    return _history_service
