"""Three-index ChromaDB setup for content generation RAG.

Three indexes serve different purposes:
1. Book Memory Index: Rolling summaries, outlines, glossary - for context
2. Draft Chunk Index: Written content - for de-duplication
3. Evidence/Claim Index: Source material and claims - for citation
"""

import logging
from typing import Any
from uuid import UUID

import chromadb
from chromadb.config import Settings as ChromaSettings

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class MultiIndexRAG:
    """Three-index RAG system for content generation.

    Manages three separate ChromaDB collections optimized for
    different retrieval patterns in the writing workflow.
    """

    def __init__(self, persist_path: str | None = None):
        """Initialize the multi-index RAG system.

        Args:
            persist_path: Path for persistent storage. Uses config default if None.
        """
        self.persist_path = persist_path or settings.chroma_persist_path

        self.client = chromadb.PersistentClient(
            path=self.persist_path,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        self._init_collections()
        logger.info(f"MultiIndexRAG initialized at {self.persist_path}")

    def _init_collections(self) -> None:
        """Create or get the three index collections."""
        self.book_memory_index = self.client.get_or_create_collection(
            name="book_memory",
            metadata={
                "hnsw:space": "cosine",
                "description": "Rolling summaries, chapter outlines, glossary",
            },
        )

        self.draft_chunk_index = self.client.get_or_create_collection(
            name="draft_chunks",
            metadata={
                "hnsw:space": "cosine",
                "description": "Draft chunks for de-duplication",
            },
        )

        self.evidence_index = self.client.get_or_create_collection(
            name="evidence_claims",
            metadata={
                "hnsw:space": "cosine",
                "description": "Evidence snippets and verified claims",
            },
        )

    def add_to_book_memory(
        self,
        doc_id: str,
        text: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document to the book memory index.

        Use for: rolling summaries, chapter outlines, glossary entries, style examples.
        """
        self.book_memory_index.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def add_to_draft_chunks(
        self,
        chunk_id: str,
        text: str,
        embedding: list[float],
        chapter_id: str,
        chapter_number: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a draft chunk to the draft index.

        Use for: de-duplication checking and finding similar passages.
        """
        meta = metadata or {}
        meta.update({"chapter_id": chapter_id, "chapter_number": chapter_number})

        self.draft_chunk_index.add(
            ids=[chunk_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )

    def add_to_evidence(
        self,
        evidence_id: str,
        text: str,
        embedding: list[float],
        source_id: str,
        claim_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add evidence or claim to the evidence index.

        Use for: retrieving supporting evidence for claims during writing.
        """
        meta = metadata or {}
        meta.update(
            {"source_id": source_id, "claim_ids": ",".join(claim_ids or [])}
        )

        self.evidence_index.add(
            ids=[evidence_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )

    def query_book_memory(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query the book memory index for context.

        Returns summaries, outlines, glossary relevant to the query.
        """
        return self.book_memory_index.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def query_draft_chunks(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        exclude_chapter_id: str | None = None,
    ) -> dict[str, Any]:
        """Query draft chunks for de-duplication checking.

        Optionally exclude the current chapter from results.
        """
        where = None
        if exclude_chapter_id:
            where = {"chapter_id": {"$ne": exclude_chapter_id}}

        return self.draft_chunk_index.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def query_evidence(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Query evidence index for supporting material.

        Optionally filter by source.
        """
        where = None
        if source_id:
            where = {"source_id": source_id}

        return self.evidence_index.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

    def get_evidence_by_ids(self, evidence_ids: list[str]) -> dict[str, Any]:
        """Get specific evidence entries by ID."""
        return self.evidence_index.get(
            ids=evidence_ids, include=["documents", "metadatas"]
        )

    def delete_collection(self, name: str) -> None:
        """Delete a collection by name."""
        try:
            self.client.delete_collection(name)
            logger.info(f"Deleted collection: {name}")
        except Exception as e:
            logger.warning(f"Failed to delete collection {name}: {e}")

    def reset_all(self) -> None:
        """Reset all collections (for testing/development)."""
        for name in ["book_memory", "draft_chunks", "evidence_claims"]:
            self.delete_collection(name)
        self._init_collections()
        logger.info("All collections reset")

    def get_stats(self) -> dict[str, int]:
        """Get document counts for all indexes."""
        return {
            "book_memory": self.book_memory_index.count(),
            "draft_chunks": self.draft_chunk_index.count(),
            "evidence": self.evidence_index.count(),
        }
