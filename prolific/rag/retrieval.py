"""Retrieval service with token budgets for writer agents.

Manages retrieval budget to keep context size manageable while
providing writers with relevant information from all three indexes.
"""

import logging
from typing import Any
from uuid import UUID

from prolific.core.config import settings
from prolific.rag.indexes import MultiIndexRAG

logger = logging.getLogger(__name__)


class WriterRetrievalService:
    """Manages retrieval budget for writer agents.

    Each writer gets a limited token budget from each index
    to prevent context overflow while maintaining coherence.
    """

    def __init__(
        self,
        rag: MultiIndexRAG,
        book_memory_budget: int | None = None,
        draft_chunk_budget: int | None = None,
        evidence_budget: int | None = None,
    ):
        """Initialize retrieval service with budget limits.

        Args:
            rag: MultiIndexRAG instance
            book_memory_budget: Token budget for book memory (default from config)
            draft_chunk_budget: Token budget for draft chunks (default from config)
            evidence_budget: Token budget for evidence (default from config)
        """
        self.rag = rag
        self.book_memory_budget = book_memory_budget or settings.book_memory_budget
        self.draft_chunk_budget = draft_chunk_budget or settings.draft_chunk_budget
        self.evidence_budget = evidence_budget or settings.evidence_budget

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text (rough heuristic: 1 token ≈ 4 chars)."""
        return len(text) // 4

    def _truncate_to_budget(
        self, documents: list[str], budget: int
    ) -> list[str]:
        """Truncate document list to fit within token budget."""
        result = []
        total_tokens = 0

        for doc in documents:
            doc_tokens = self._estimate_tokens(doc)
            if total_tokens + doc_tokens <= budget:
                result.append(doc)
                total_tokens += doc_tokens
            else:
                remaining = budget - total_tokens
                if remaining > 100:
                    truncated = doc[: remaining * 4]
                    result.append(truncated + "...")
                break

        return result

    async def retrieve_for_writer(
        self,
        query_embedding: list[float],
        chapter_id: str,
        required_claim_ids: list[str] | None = None,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve context for a writer within budget constraints.

        Args:
            query_embedding: Embedding of the chapter brief/topic
            chapter_id: Current chapter ID (excluded from de-dup check)
            required_claim_ids: Claim IDs that must be included
            thread_id: Thread ID to filter by (prevents cross-contamination)

        Returns:
            Dict with book_context, similar_drafts, evidence, and flags
        """
        results = {
            "book_context": [],
            "similar_drafts": [],
            "evidence": [],
            "repetition_warnings": [],
        }

        book_results = self.rag.query_book_memory(
            query_embedding=query_embedding, n_results=10, thread_id=thread_id
        )
        if book_results["documents"] and book_results["documents"][0]:
            results["book_context"] = self._truncate_to_budget(
                book_results["documents"][0], self.book_memory_budget
            )

        draft_results = self.rag.query_draft_chunks(
            query_embedding=query_embedding,
            n_results=15,
            exclude_chapter_id=chapter_id,
            thread_id=thread_id,
        )
        if draft_results["documents"] and draft_results["documents"][0]:
            for doc, dist, meta in zip(
                draft_results["documents"][0],
                draft_results["distances"][0],
                draft_results["metadatas"][0],
            ):
                similarity = 1 - dist
                entry = {
                    "text": doc,
                    "similarity": similarity,
                    "chapter_number": meta.get("chapter_number", "unknown"),
                    "avoid": similarity > 0.70,
                }
                results["similar_drafts"].append(entry)

                if similarity > 0.70:
                    results["repetition_warnings"].append(
                        f"High similarity ({similarity:.0%}) with chapter "
                        f"{meta.get('chapter_number', 'unknown')}"
                    )

            draft_texts = [d["text"] for d in results["similar_drafts"]]
            results["similar_drafts_text"] = self._truncate_to_budget(
                draft_texts, self.draft_chunk_budget
            )

        if required_claim_ids:
            evidence_results = self.rag.get_evidence_by_ids(required_claim_ids)
            if evidence_results["documents"]:
                results["evidence"] = self._truncate_to_budget(
                    evidence_results["documents"], self.evidence_budget
                )

        evidence_query_results = self.rag.query_evidence(
            query_embedding=query_embedding, n_results=20, thread_id=thread_id
        )
        if evidence_query_results["documents"] and evidence_query_results["documents"][0]:
            remaining_budget = self.evidence_budget - sum(
                self._estimate_tokens(e) for e in results["evidence"]
            )
            if remaining_budget > 0:
                additional = self._truncate_to_budget(
                    evidence_query_results["documents"][0], remaining_budget
                )
                results["evidence"].extend(additional)

        return results

    def build_writer_context(self, retrieval_results: dict[str, Any]) -> str:
        """Build a formatted context string for the writer from retrieval results.

        Args:
            retrieval_results: Output from retrieve_for_writer

        Returns:
            Formatted context string for the writer prompt
        """
        sections = []

        if retrieval_results.get("book_context"):
            sections.append("## Book Context (What's Already Written)")
            for ctx in retrieval_results["book_context"]:
                sections.append(f"- {ctx}")
            sections.append("")

        if retrieval_results.get("repetition_warnings"):
            sections.append("## AVOID REPETITION - Similar Content Exists:")
            for warning in retrieval_results["repetition_warnings"]:
                sections.append(f"⚠️ {warning}")
            sections.append("")

        if retrieval_results.get("evidence"):
            sections.append("## Supporting Evidence (Use for Citations)")
            for i, evidence in enumerate(retrieval_results["evidence"], 1):
                sections.append(f"{i}. {evidence}")
            sections.append("")

        return "\n".join(sections)
