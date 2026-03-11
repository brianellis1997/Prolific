"""SQLite-backed channel history for tracking past video topics."""

import json
import logging
import aiosqlite

from prolific.core.config import settings
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
                    is_biography INTEGER DEFAULT 0
                )
            """)
            await db.commit()

    async def record_video(self, record: VideoRecord) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO videos
                   (id, topic, title, description, tags, youtube_video_id,
                    youtube_url, thumbnail_path, video_path, script_word_count,
                    estimated_duration_minutes, status, created_at, published_at,
                    era_tags, region_tags, is_biography)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                ),
            )
            await db.commit()

    async def get_past_topics(self, limit: int = 200) -> list[str]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT topic FROM videos ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def get_past_videos(self, limit: int = 50) -> list[VideoRecord]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
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


_channel_history_service: ChannelHistoryService | None = None


def get_channel_history_service() -> ChannelHistoryService:
    global _channel_history_service
    if _channel_history_service is None:
        _channel_history_service = ChannelHistoryService()
    return _channel_history_service
