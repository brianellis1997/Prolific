"""Retrieval service with token budgets for writer agents.

Manages retrieval budget to keep context size manageable while
providing writers with relevant information from all three indexes.
Budgets scale with section word count for longer documents.
"""

import logging
from typing import Any
from uuid import UUID

from prolific.core.config import settings
from prolific.rag.indexes import MultiIndexRAG

logger = logging.getLogger(__name__)

BASE_SECTION_WORDS = 2000
BASE_EVIDENCE_BUDGET = 4000
MIN_EVIDENCE_BUDGET = 2000
MAX_EVIDENCE_BUDGET = 8000


class WriterRetrievalService:
    """Manages retrieval budget for writer agents.

    Each writer gets a limited token budget from each index
    to prevent context overflow while maintaining coherence.
    Budgets scale proportionally with section word count targets.
    """

    def __init__(
        self,
        rag: MultiIndexRAG,
        book_memory_budget: int | None = None,
        draft_chunk_budget: int | None = None,
        base_evidence_budget: int | None = None,
        previous_content_budget: int | None = None,
    ):
        """Initialize retrieval service with budget limits.

        Args:
            rag: MultiIndexRAG instance
            book_memory_budget: Token budget for book memory (default from config)
            draft_chunk_budget: Token budget for draft chunks (default from config)
            base_evidence_budget: Base token budget for evidence (scales with word count)
            previous_content_budget: Token budget for previous chapter content (default 1500)
        """
        self.rag = rag
        self.book_memory_budget = book_memory_budget or settings.book_memory_budget
        self.draft_chunk_budget = draft_chunk_budget or settings.draft_chunk_budget
        self.base_evidence_budget = base_evidence_budget or settings.evidence_budget
        self.previous_content_budget = previous_content_budget or 1500

    def _calculate_evidence_budget(self, section_word_target: int) -> int:
        """Calculate evidence budget scaled to section word count.

        Args:
            section_word_target: Target word count for the section

        Returns:
            Scaled evidence budget (clamped between min/max)
        """
        if section_word_target <= 0:
            return self.base_evidence_budget

        scale_factor = section_word_target / BASE_SECTION_WORDS
        scaled_budget = int(self.base_evidence_budget * scale_factor)

        return max(MIN_EVIDENCE_BUDGET, min(MAX_EVIDENCE_BUDGET, scaled_budget))

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
        section_word_target: int = BASE_SECTION_WORDS,
    ) -> dict[str, Any]:
        """Retrieve context for a writer within budget constraints.

        Args:
            query_embedding: Embedding of the chapter brief/topic
            chapter_id: Current chapter ID (excluded from de-dup check)
            required_claim_ids: Claim IDs that must be included
            thread_id: Thread ID to filter by (prevents cross-contamination)
            section_word_target: Target word count for the section (scales evidence budget)

        Returns:
            Dict with book_context, similar_drafts, evidence, and flags
        """
        evidence_budget = self._calculate_evidence_budget(section_word_target)
        logger.debug(
            f"Evidence budget: {evidence_budget} tokens "
            f"(scaled for {section_word_target} word target)"
        )

        results = {
            "book_context": [],
            "similar_drafts": [],
            "previous_content": [],
            "evidence": [],
            "repetition_warnings": [],
            "evidence_budget_used": evidence_budget,
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
            relevant_snippets = []
            for doc, dist, meta in zip(
                draft_results["documents"][0],
                draft_results["distances"][0],
                draft_results["metadatas"][0],
            ):
                similarity = 1 - dist
                chapter_num = meta.get("chapter_number", "unknown")
                entry = {
                    "text": doc,
                    "similarity": similarity,
                    "chapter_number": chapter_num,
                    "avoid": similarity > 0.70,
                }
                results["similar_drafts"].append(entry)

                if similarity > 0.70:
                    results["repetition_warnings"].append(
                        f"High similarity ({similarity:.0%}) with chapter {chapter_num}"
                    )

                if 0.40 <= similarity <= 0.70:
                    relevant_snippets.append({
                        "text": doc[:800],
                        "chapter_number": chapter_num,
                        "similarity": similarity,
                    })

            results["previous_content"] = relevant_snippets[:5]

            draft_texts = [d["text"] for d in results["similar_drafts"]]
            results["similar_drafts_text"] = self._truncate_to_budget(
                draft_texts, self.draft_chunk_budget
            )

        if required_claim_ids:
            evidence_results = self.rag.get_evidence_by_ids(required_claim_ids)
            if evidence_results["documents"]:
                results["evidence"] = self._truncate_to_budget(
                    evidence_results["documents"], evidence_budget
                )

        evidence_query_results = self.rag.query_evidence(
            query_embedding=query_embedding, n_results=20, thread_id=thread_id
        )
        if evidence_query_results["documents"] and evidence_query_results["documents"][0]:
            remaining_budget = evidence_budget - sum(
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

        if retrieval_results.get("previous_content"):
            sections.append("## Relevant Content from Previous Chapters (reference but don't repeat)")
            for snippet in retrieval_results["previous_content"]:
                chapter_num = snippet.get("chapter_number", "?")
                text = snippet.get("text", "")
                sections.append(f"**Chapter {chapter_num}:**")
                sections.append(f'"{text}..."')
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
