"""Checkpointer service for persistence and recovery of generation runs.

Uses LangGraph's AsyncSqliteSaver for SQLite-based checkpointing.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from prolific.core.config import settings

logger = logging.getLogger(__name__)

CHECKPOINT_DB_PATH = Path(settings.chroma_persist_path).parent / "checkpoints.sqlite"


class CheckpointerService:
    """Manages checkpointing for content generation runs."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        """Initialize the checkpointer service.

        Args:
            db_path: Path to SQLite database. Defaults to checkpoints.sqlite
        """
        self.db_path = str(db_path or CHECKPOINT_DB_PATH)
        self._saver: AsyncSqliteSaver | None = None
        self._conn_manager = None
        self._metadata_initialized = False

    async def _ensure_metadata_table(self) -> None:
        """Ensure the thread_metadata table exists."""
        if self._metadata_initialized:
            return

        saver = await self.get_saver()
        await saver.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_metadata (
                thread_id TEXT PRIMARY KEY,
                topic TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        await saver.conn.commit()
        self._metadata_initialized = True

    async def get_saver(self) -> AsyncSqliteSaver:
        """Get or create the AsyncSqliteSaver instance."""
        if self._saver is None:
            self._conn_manager = AsyncSqliteSaver.from_conn_string(self.db_path)
            self._saver = await self._conn_manager.__aenter__()
        return self._saver

    async def close(self) -> None:
        """Close the checkpointer connection."""
        if self._conn_manager is not None:
            await self._conn_manager.__aexit__(None, None, None)
            self._saver = None
            self._conn_manager = None

    def generate_thread_id(self) -> str:
        """Generate a unique thread ID for a new generation run."""
        return str(uuid4())

    async def register_thread(self, thread_id: str, topic: str) -> None:
        """Register a new thread with metadata.

        Args:
            thread_id: The thread ID
            topic: The topic for this generation
        """
        await self._ensure_metadata_table()
        saver = await self.get_saver()

        created_at = datetime.utcnow().isoformat()
        try:
            await saver.conn.execute(
                """
                INSERT OR REPLACE INTO thread_metadata (thread_id, topic, created_at)
                VALUES (?, ?, ?)
                """,
                (thread_id, topic, created_at)
            )
            await saver.conn.commit()
        except Exception as e:
            logger.warning(f"Failed to register thread metadata: {e}")

    async def list_threads(self) -> list:
        """List all generation threads with their latest checkpoint info.

        Returns:
            List of thread info dicts with id, topic, phase, timestamp
        """
        await self._ensure_metadata_table()
        saver = await self.get_saver()

        threads = []
        try:
            async with saver.conn.execute(
                """
                SELECT DISTINCT c.thread_id, m.created_at
                FROM checkpoints c
                LEFT JOIN thread_metadata m ON c.thread_id = m.thread_id
                ORDER BY COALESCE(m.created_at, c.thread_id) DESC
                """
            ) as cursor:
                thread_rows = [(row[0], row[1]) async for row in cursor]

            for thread_id, created_at in thread_rows:
                config = {"configurable": {"thread_id": thread_id}}
                checkpoint = await saver.aget(config)
                if checkpoint:
                    channel_values = checkpoint.get("channel_values", {})
                    threads.append({
                        "thread_id": thread_id,
                        "topic": channel_values.get("topic", "Unknown"),
                        "phase": channel_values.get("current_phase", "unknown"),
                        "iteration": channel_values.get("iteration_count", 0),
                        "word_count": sum(
                            c.word_count
                            for c in channel_values.get("draft_chunks", [])
                        ),
                        "chapter_count": len(channel_values.get("draft_chunks", [])),
                        "source_count": len(channel_values.get("approved_sources", [])),
                        "claim_count": len(channel_values.get("claims", [])),
                        "created_at": created_at,
                    })
        except Exception as e:
            logger.warning(f"Failed to list threads: {e}")

        return threads

    async def get_thread_state(self, thread_id: str) -> dict | None:
        """Get the latest state for a thread.

        Args:
            thread_id: The thread ID to retrieve

        Returns:
            The checkpoint channel_values or None if not found
        """
        saver = await self.get_saver()
        config = {"configurable": {"thread_id": thread_id}}

        checkpoint = await saver.aget(config)
        if checkpoint:
            return checkpoint.get("channel_values")
        return None

    async def delete_thread(self, thread_id: str) -> bool:
        """Delete all checkpoints for a thread.

        Args:
            thread_id: The thread ID to delete

        Returns:
            True if deleted, False if not found
        """
        await self._ensure_metadata_table()
        saver = await self.get_saver()
        try:
            await saver.conn.execute(
                "DELETE FROM checkpoints WHERE thread_id = ?",
                (thread_id,)
            )
            await saver.conn.execute(
                "DELETE FROM checkpoint_writes WHERE thread_id = ?",
                (thread_id,)
            )
            await saver.conn.execute(
                "DELETE FROM thread_metadata WHERE thread_id = ?",
                (thread_id,)
            )
            await saver.conn.commit()
            logger.info(f"Deleted thread {thread_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete thread {thread_id}: {e}")
            return False


_checkpointer_service: CheckpointerService | None = None


def get_checkpointer_service() -> CheckpointerService:
    """Get the singleton checkpointer service."""
    global _checkpointer_service
    if _checkpointer_service is None:
        _checkpointer_service = CheckpointerService()
    return _checkpointer_service
