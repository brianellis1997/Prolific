"""De-duplication gate for preventing repetitive content.

Checks new draft chunks against existing content to prevent
repetition across chapters using n-gram overlap detection.
"""

import logging
import re
from dataclasses import dataclass

from prolific.rag.indexes import MultiIndexRAG

logger = logging.getLogger(__name__)


def extract_ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    """Extract word n-grams from text.

    Args:
        text: Input text
        n: Size of n-grams (default 4 words)

    Returns:
        Set of n-gram tuples
    """
    words = re.findall(r'\b\w+\b', text.lower())
    if len(words) < n:
        return set()
    return {tuple(words[i:i+n]) for i in range(len(words) - n + 1)}


def ngram_overlap_score(text1: str, text2: str, n: int = 4) -> float:
    """Calculate Jaccard similarity of n-grams between two texts.

    This detects actual phrase/sentence repetition rather than
    semantic similarity, which reduces false positives.

    Args:
        text1: First text
        text2: Second text
        n: Size of n-grams (default 4 words)

    Returns:
        Jaccard similarity score (0.0 to 1.0)
    """
    ngrams1 = extract_ngrams(text1, n)
    ngrams2 = extract_ngrams(text2, n)

    if not ngrams1 or not ngrams2:
        return 0.0

    intersection = len(ngrams1 & ngrams2)
    union = len(ngrams1 | ngrams2)

    return intersection / union if union > 0 else 0.0


@dataclass
class DeduplicationResult:
    """Result from de-duplication check."""

    is_acceptable: bool
    similarity_score: float
    similar_chapter: str | None
    warnings: list[str]
    rejection_reason: str | None


class DeduplicationGate:
    """Prevents repetitive content using n-gram overlap detection.

    Uses n-gram Jaccard similarity to detect actual text repetition
    rather than semantic similarity (which gives too many false positives
    for chapters covering related topics).
    """

    REJECTION_THRESHOLD = 0.15  # Reject if > 15% n-gram overlap (actual repetition)
    WARNING_THRESHOLD = 0.08   # Warn if > 8% n-gram overlap

    def __init__(
        self,
        rag: MultiIndexRAG,
        rejection_threshold: float | None = None,
        warning_threshold: float | None = None,
    ):
        """Initialize the de-duplication gate.

        Args:
            rag: MultiIndexRAG instance
            rejection_threshold: N-gram overlap above this = reject (default 0.15)
            warning_threshold: N-gram overlap above this = warn (default 0.08)
        """
        self.rag = rag
        self.rejection_threshold = rejection_threshold or self.REJECTION_THRESHOLD
        self.warning_threshold = warning_threshold or self.WARNING_THRESHOLD
        self._existing_chunks: dict[str, str] = {}

    def add_chunk(self, chapter_id: str, content: str):
        """Add a chunk to the comparison set.

        Args:
            chapter_id: Chapter identifier
            content: Chunk content
        """
        self._existing_chunks[chapter_id] = content

    async def check_chunk(
        self,
        chunk_embedding: list[float],
        chapter_id: str,
        chunk_content: str | None = None,
        thread_id: str | None = None,
    ) -> DeduplicationResult:
        """Check if a draft chunk has too much text repetition.

        Uses n-gram overlap rather than embedding similarity for
        more accurate repetition detection.

        Args:
            chunk_embedding: Embedding of the new chunk (for RAG retrieval)
            chapter_id: Current chapter ID (excluded from comparison)
            chunk_content: The actual text content for n-gram comparison
            thread_id: Thread ID to filter by (prevents cross-contamination)

        Returns:
            DeduplicationResult with acceptance status and warnings
        """
        if not chunk_content:
            return DeduplicationResult(
                is_acceptable=True,
                similarity_score=0.0,
                similar_chapter=None,
                warnings=[],
                rejection_reason=None,
            )

        results = self.rag.query_draft_chunks(
            query_embedding=chunk_embedding,
            n_results=5,
            exclude_chapter_id=chapter_id,
            thread_id=thread_id,
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
        max_overlap = 0.0
        most_similar_chapter = None

        for doc, meta in zip(
            results["documents"][0],
            results["metadatas"][0],
        ):
            chapter_num = meta.get("chapter_number", "unknown")

            overlap = ngram_overlap_score(chunk_content, doc, n=4)

            if overlap > max_overlap:
                max_overlap = overlap
                most_similar_chapter = str(chapter_num)

            if overlap > self.rejection_threshold:
                logger.warning(
                    f"Content rejected: {overlap:.1%} n-gram overlap with chapter {chapter_num}"
                )
                return DeduplicationResult(
                    is_acceptable=False,
                    similarity_score=overlap,
                    similar_chapter=str(chapter_num),
                    warnings=[],
                    rejection_reason=(
                        f"Content has {overlap:.1%} text overlap with chapter {chapter_num}. "
                        "Significant rephrasing needed to avoid repetition."
                    ),
                )

            if overlap > self.warning_threshold:
                warnings.append(
                    f"Content has {overlap:.1%} text overlap with chapter {chapter_num}. "
                    "Consider varying the phrasing."
                )

        return DeduplicationResult(
            is_acceptable=True,
            similarity_score=max_overlap,
            similar_chapter=most_similar_chapter,
            warnings=warnings,
            rejection_reason=None,
        )

    async def check_text(
        self,
        text: str,
        chapter_id: str,
        embedding_fn,
        thread_id: str | None = None,
    ) -> DeduplicationResult:
        """Convenience method that generates embedding and checks.

        Args:
            text: Text to check
            chapter_id: Current chapter ID
            embedding_fn: Async function to generate embedding from text
            thread_id: Thread ID to filter by (prevents cross-contamination)

        Returns:
            DeduplicationResult
        """
        embedding = await embedding_fn(text)
        return await self.check_chunk(embedding, chapter_id, chunk_content=text, thread_id=thread_id)
