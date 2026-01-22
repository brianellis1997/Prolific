"""De-duplication gate for preventing repetitive content.

Checks new draft chunks against existing content to prevent
repetition across chapters.
"""

import logging
from dataclasses import dataclass

from prolific.rag.indexes import MultiIndexRAG

logger = logging.getLogger(__name__)


@dataclass
class DeduplicationResult:
    """Result from de-duplication check."""

    is_acceptable: bool
    similarity_score: float
    similar_chapter: str | None
    warnings: list[str]
    rejection_reason: str | None


class DeduplicationGate:
    """Prevents repetitive content by checking against existing drafts.

    Uses similarity thresholds to either warn or reject new content
    that's too similar to what's already been written.
    """

    REJECTION_THRESHOLD = 0.85  # Reject if > 85% similar
    WARNING_THRESHOLD = 0.70  # Warn if > 70% similar

    def __init__(
        self,
        rag: MultiIndexRAG,
        rejection_threshold: float | None = None,
        warning_threshold: float | None = None,
    ):
        """Initialize the de-duplication gate.

        Args:
            rag: MultiIndexRAG instance
            rejection_threshold: Similarity above this = reject (default 0.85)
            warning_threshold: Similarity above this = warn (default 0.70)
        """
        self.rag = rag
        self.rejection_threshold = rejection_threshold or self.REJECTION_THRESHOLD
        self.warning_threshold = warning_threshold or self.WARNING_THRESHOLD

    async def check_chunk(
        self,
        chunk_embedding: list[float],
        chapter_id: str,
    ) -> DeduplicationResult:
        """Check if a draft chunk is too similar to existing content.

        Args:
            chunk_embedding: Embedding of the new chunk
            chapter_id: Current chapter ID (excluded from comparison)

        Returns:
            DeduplicationResult with acceptance status and warnings
        """
        results = self.rag.query_draft_chunks(
            query_embedding=chunk_embedding,
            n_results=5,
            exclude_chapter_id=chapter_id,
        )

        if not results["documents"] or not results["documents"][0]:
            return DeduplicationResult(
                is_acceptable=True,
                similarity_score=0.0,
                similar_chapter=None,
                warnings=[],
                rejection_reason=None,
            )

        warnings = []
        max_similarity = 0.0
        most_similar_chapter = None

        for doc, dist, meta in zip(
            results["documents"][0],
            results["distances"][0],
            results["metadatas"][0],
        ):
            similarity = 1 - dist
            chapter_num = meta.get("chapter_number", "unknown")

            if similarity > max_similarity:
                max_similarity = similarity
                most_similar_chapter = str(chapter_num)

            if similarity > self.rejection_threshold:
                logger.warning(
                    f"Content rejected: {similarity:.0%} similar to chapter {chapter_num}"
                )
                return DeduplicationResult(
                    is_acceptable=False,
                    similarity_score=similarity,
                    similar_chapter=str(chapter_num),
                    warnings=[],
                    rejection_reason=(
                        f"Content is {similarity:.0%} similar to chapter {chapter_num}. "
                        "Please rephrase significantly or add unique insights."
                    ),
                )

            if similarity > self.warning_threshold:
                warnings.append(
                    f"Content is {similarity:.0%} similar to chapter {chapter_num}. "
                    "Consider rephrasing for variety."
                )

        return DeduplicationResult(
            is_acceptable=True,
            similarity_score=max_similarity,
            similar_chapter=most_similar_chapter,
            warnings=warnings,
            rejection_reason=None,
        )

    async def check_text(
        self,
        text: str,
        chapter_id: str,
        embedding_fn,
    ) -> DeduplicationResult:
        """Convenience method that generates embedding and checks.

        Args:
            text: Text to check
            chapter_id: Current chapter ID
            embedding_fn: Async function to generate embedding from text

        Returns:
            DeduplicationResult
        """
        embedding = await embedding_fn(text)
        return await self.check_chunk(embedding, chapter_id)
