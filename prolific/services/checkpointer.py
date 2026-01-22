"""Checkpointer service for persistence and recovery of generation runs.

Uses LangGraph's AsyncSqliteSaver for SQLite-based checkpointing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union
from uuid import uuid4

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

    async def get_saver(self) -> AsyncSqliteSaver:
        """Get or create the AsyncSqliteSaver instance."""
        if self._saver is None:
            self._saver = AsyncSqliteSaver.from_conn_string(self.db_path)
            await self._saver.setup()
        return self._saver

    async def close(self) -> None:
        """Close the checkpointer connection."""
        if self._saver is not None:
            await self._saver.conn.close()
            self._saver = None

    @staticmethod
    def generate_thread_id() -> str:
        """Generate a unique thread ID for a new generation run."""
        return str(uuid4())

    async def list_threads(self) -> list:
        """List all generation threads with their latest checkpoint info.

        Returns:
            List of thread info dicts with id, topic, phase, timestamp
        """
        saver = await self.get_saver()

        threads = []
        try:
            async with saver.conn.execute(
                """
                SELECT DISTINCT thread_id
                FROM checkpoints
                ORDER BY thread_ts DESC
                """
            ) as cursor:
                thread_ids = [row[0] async for row in cursor]

            for thread_id in thread_ids:
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
