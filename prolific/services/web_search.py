"""Web search service using Tavily API.

Tavily is purpose-built for AI agents and returns clean,
well-structured results optimized for LLM consumption.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from tavily import AsyncTavilyClient

from prolific.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    url: str
    title: str
    snippet: str
    score: float
    raw_content: str | None = None


class WebSearchService:
    """Service for web search using Tavily API.

    Provides AI-optimized search results for research agents.
    """

    def __init__(self, api_key: str | None = None):
        """Initialize web search service.

        Args:
            api_key: Tavily API key (default from config)
        """
        self.api_key = api_key or settings.tavily_api_key
        self._client = AsyncTavilyClient(api_key=self.api_key)
        logger.info("WebSearchService initialized with Tavily")

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_depth: Literal["basic", "advanced"] = "basic",
        include_raw_content: bool = False,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the web for relevant sources.

        Args:
            query: Search query
            max_results: Maximum number of results (default 10)
            search_depth: "basic" for faster, "advanced" for more thorough
            include_raw_content: Whether to include full page content
            include_domains: Only search these domains
            exclude_domains: Exclude these domains

        Returns:
            List of SearchResult objects
        """
        try:
            response = await self._client.search(
                query=query,
                max_results=max_results,
                search_depth=search_depth,
                include_raw_content=include_raw_content,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )

            results = []
            for item in response.get("results", []):
                results.append(
                    SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        snippet=item.get("content", ""),
                        score=item.get("score", 0.0),
                        raw_content=item.get("raw_content"),
                    )
                )

            logger.info(f"Search for '{query}' returned {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            raise

    async def search_with_context(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict:
        """Search and return results with AI-generated context summary.

        Uses Tavily's context feature for pre-processed results.

        Args:
            query: Search query
            max_results: Maximum results

        Returns:
            Dict with 'results' and 'context' (AI summary)
        """
        try:
            response = await self._client.get_search_context(
                query=query,
                max_results=max_results,
            )
            return {"context": response, "query": query}
        except Exception as e:
            logger.error(f"Context search failed for '{query}': {e}")
            raise


_web_search_service: WebSearchService | None = None


def get_web_search_service() -> WebSearchService:
    """Get the singleton web search service instance."""
    global _web_search_service
    if _web_search_service is None:
        _web_search_service = WebSearchService()
    return _web_search_service
