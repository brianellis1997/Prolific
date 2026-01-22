"""Embedding service for generating vector representations.

Uses OpenAI's text-embedding-3-small for cost-effective embeddings.
"""

import logging
from typing import Sequence

from langchain_openai import OpenAIEmbeddings

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings.

    Uses OpenAI's embedding API for consistent, high-quality embeddings
    across all indexing and retrieval operations.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """Initialize embedding service.

        Args:
            api_key: OpenAI API key (default from config)
            model: Embedding model name (default from config)
        """
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.embedding_model

        self._embeddings = OpenAIEmbeddings(
            api_key=self.api_key,
            model=self.model,
        )
        logger.info(f"EmbeddingService initialized with model: {self.model}")

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats
        """
        return await self._embeddings.aembed_query(text)

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: Sequence of texts to embed

        Returns:
            List of embedding vectors
        """
        return await self._embeddings.aembed_documents(list(texts))

    def embed_text_sync(self, text: str) -> list[float]:
        """Generate embedding synchronously (for non-async contexts).

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        return self._embeddings.embed_query(text)

    def embed_texts_sync(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate embeddings synchronously for multiple texts.

        Args:
            texts: Sequence of texts to embed

        Returns:
            List of embedding vectors
        """
        return self._embeddings.embed_documents(list(texts))


_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get the singleton embedding service instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
