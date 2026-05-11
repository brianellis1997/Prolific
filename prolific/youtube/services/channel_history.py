"""SQLite-backed channel history for tracking past video topics."""

import json
import logging
from datetime import datetime
import aiosqlite
import numpy as np

from prolific.core.config import settings
from prolific.services.topic_dedup import (
    PastTopicEmbedding,
    blob_to_embedding,
    embedding_to_blob,
)
from prolific.youtube.schemas import VideoRecord

logger = logging.getLogger(__name__)


class ChannelHistoryService:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or settings.youtube_history_db_path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    youtube_video_id TEXT,
                    youtube_url TEXT,
                    thumbnail_path TEXT,
                    video_path TEXT,
                    script_word_count INTEGER DEFAULT 0,
                    estimated_duration_minutes REAL DEFAULT 0,
                    status TEXT DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    published_at TEXT,
                    era_tags TEXT NOT NULL DEFAULT '[]',
                    region_tags TEXT NOT NULL DEFAULT '[]',
                    is_biography INTEGER DEFAULT 0,
                    selection_rationale TEXT DEFAULT ''
                )
            """)
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN selection_rationale TEXT DEFAULT ''")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN embedding BLOB")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN embedding_model_version TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN content_mode TEXT DEFAULT 'BIOGRAPHY'")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN entities TEXT DEFAULT '[]'")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE videos ADD COLUMN thumbnail_hook TEXT DEFAULT ''")
            except Exception:
                pass
            # Idempotent backfill: derive content_mode from is_biography for legacy rows.
            await db.execute(
                """UPDATE videos
                   SET content_mode = CASE WHEN is_biography = 1 THEN 'BIOGRAPHY' ELSE 'BROAD_TOPIC' END
                   WHERE content_mode IS NULL OR content_mode = ''"""
            )
            await db.commit()

    async def record_video(self, record: VideoRecord) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO videos
                   (id, topic, title, description, tags, youtube_video_id,
                    youtube_url, thumbnail_path, video_path, script_word_count,
                    estimated_duration_minutes, status, created_at, published_at,
                    era_tags, region_tags, is_biography, selection_rationale, content_mode,
                    thumbnail_hook)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(record.id),
                    record.topic,
                    record.title,
                    record.description,
                    json.dumps(record.tags),
                    record.youtube_video_id,
                    record.youtube_url,
                    record.thumbnail_path,
                    record.video_path,
                    record.script_word_count,
                    record.estimated_duration_minutes,
                    record.status,
                    record.created_at.isoformat(),
                    record.published_at.isoformat() if record.published_at else None,
                    json.dumps(record.era_tags),
                    json.dumps(record.region_tags),
                    1 if record.is_biography else 0,
                    record.selection_rationale,
                    record.content_mode,
                    record.thumbnail_hook or "",
                ),
            )
            await db.commit()

    async def get_recent_thumbnail_hooks(self, limit: int = 7) -> list[tuple[str, str]]:
        """Return (hook, topic) for the most recent N videos that have a hook stored.

        Used by thumbnail_generation_node to pass a DO-NOT-REPEAT list into the
        brainstorm prompt so the model stops verbatim-recycling reference hooks
        across consecutive videos (e.g. shipping 'WE CAN'T EXPLAIN THIS' three
        times in five days, which is what triggered this method).
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """SELECT thumbnail_hook, topic FROM videos
                   WHERE thumbnail_hook IS NOT NULL AND thumbnail_hook != ''
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [(row[0], row[1]) for row in rows]

    async def get_past_topics(self, limit: int = 200) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT topic FROM videos ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_past_videos(self, limit: int = 50, content_mode: str | None = None) -> list[VideoRecord]:
        """Pull past videos, optionally filtered by content_mode.

        When `content_mode` is provided, only videos matching that mode are returned —
        used by topic_selection to avoid cross-mode era/region tag pollution in the
        diversity context.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if content_mode is not None:
                cursor = await db.execute(
                    "SELECT * FROM videos WHERE content_mode = ? ORDER BY created_at DESC LIMIT ?",
                    (content_mode, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    VideoRecord(
                        id=row["id"],
                        topic=row["topic"],
                        title=row["title"],
                        description=row["description"],
                        tags=json.loads(row["tags"]),
                        youtube_video_id=row["youtube_video_id"],
                        youtube_url=row["youtube_url"],
                        thumbnail_path=row["thumbnail_path"],
                        video_path=row["video_path"],
                        script_word_count=row["script_word_count"],
                        estimated_duration_minutes=row["estimated_duration_minutes"],
                        status=row["status"],
                        era_tags=json.loads(row["era_tags"]),
                        region_tags=json.loads(row["region_tags"]),
                        is_biography=bool(row["is_biography"]),
                        content_mode=row["content_mode"] or "BIOGRAPHY",
                    )
                )
            return results

    async def get_biography_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM videos WHERE is_biography = 1"
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_total_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM videos")
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_count_by_mode(self, content_mode: str) -> int:
        """Count videos for a specific content_mode (used to compute per-mode bio_ratio)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM videos WHERE content_mode = ?",
                (content_mode,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_videos_by_mode(self, content_mode: str, limit: int = 50) -> list[VideoRecord]:
        """Filter analytics to a single content_mode (used by /api/v1/youtube/history?content_mode=X)."""
        return await self.get_past_videos(limit=limit, content_mode=content_mode)

    async def get_past_topics_with_embeddings(self, limit: int = 200) -> list[PastTopicEmbedding]:
        """Pull past videos with cached embeddings for the dedup gate.

        Records with null embeddings are returned as-is — the caller hydrates
        them via topic_dedup.hydrate_embeddings. v2: also pulls description
        (used as script_excerpt for rich-content embeddings) and entities.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT id, youtube_video_id, topic, title, description, selection_rationale,
                          published_at, embedding, embedding_model_version, entities, content_mode
                   FROM videos
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
                try:
                    entities = json.loads(row["entities"] or "[]")
                except Exception:
                    entities = []
                results.append(
                    PastTopicEmbedding(
                        video_id=row["youtube_video_id"] or row["id"],
                        topic=row["topic"],
                        title=row["title"] or row["topic"],
                        published_at=pub_at,
                        embedding=blob_to_embedding(row["embedding"]),
                        embedding_model_version=row["embedding_model_version"],
                        script_excerpt=(row["description"] or "")[:5000],
                        entities=entities,
                        content_mode=row["content_mode"] or "BIOGRAPHY",
                    )
                )
            return results

    async def update_entities(self, video_id: str, entities: list[str]) -> None:
        """Persist extracted canonical entities for a published video."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE videos
                   SET entities = ?
                   WHERE youtube_video_id = ? OR id = ?""",
                (json.dumps(entities), video_id, video_id),
            )
            await db.commit()

    async def update_embedding(
        self, video_id: str, embedding: np.ndarray, model_version: str
    ) -> None:
        """Persist a cached embedding for a published video.

        `video_id` matches `youtube_video_id` (the YouTube ID, not the internal
        UUID) — that's what topic_dedup uses as its public ID.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE videos
                   SET embedding = ?, embedding_model_version = ?
                   WHERE youtube_video_id = ? OR id = ?""",
                (embedding_to_blob(embedding), model_version, video_id, video_id),
            )
            await db.commit()

    async def get_video_by_id(self, video_id: str) -> VideoRecord | None:
        """Look up a video by `youtube_video_id` or internal UUID. Used for
        Part 2 parent-title lookup in metadata_generation."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM videos WHERE youtube_video_id = ? OR id = ? LIMIT 1",
                (video_id, video_id),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return VideoRecord(
                id=row["id"],
                topic=row["topic"],
                title=row["title"],
                description=row["description"],
                tags=json.loads(row["tags"]),
                youtube_video_id=row["youtube_video_id"],
                youtube_url=row["youtube_url"],
                thumbnail_path=row["thumbnail_path"],
                video_path=row["video_path"],
                script_word_count=row["script_word_count"],
                estimated_duration_minutes=row["estimated_duration_minutes"],
                status=row["status"],
                era_tags=json.loads(row["era_tags"]),
                region_tags=json.loads(row["region_tags"]),
                is_biography=bool(row["is_biography"]),
                content_mode=row["content_mode"] or "BIOGRAPHY",
            )


_channel_history_service: ChannelHistoryService | None = None


def get_channel_history_service() -> ChannelHistoryService:
    global _channel_history_service
    if _channel_history_service is None:
        _channel_history_service = ChannelHistoryService()
    return _channel_history_service
