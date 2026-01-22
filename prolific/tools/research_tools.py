"""Research tools for the Research Agent.

These tools enable web search, academic search, and content fetching
for discovering and gathering source material.
"""

import logging
from typing import Literal

from langchain_core.tools import tool

from prolific.services.web_fetch import get_web_fetch_service
from prolific.services.web_search import get_web_search_service

logger = logging.getLogger(__name__)


@tool
async def web_search(
    query: str,
    max_results: int = 10,
    search_depth: Literal["basic", "advanced"] = "basic",
) -> list[dict]:
    """Search the web for sources on a topic.

    Use this to find relevant web pages, articles, and documents
    on the research topic.

    Args:
        query: Search query string (be specific for better results)
        max_results: Number of results to return (default 10, max 20)
        search_depth: "basic" for quick search, "advanced" for more thorough

    Returns:
        List of search results with url, title, snippet, and score
    """
    service = get_web_search_service()
    results = await service.search(
        query=query,
        max_results=min(max_results, 20),
        search_depth=search_depth,
    )

    return [
        {
            "url": r.url,
            "title": r.title,
            "snippet": r.snippet,
            "score": r.score,
        }
        for r in results
    ]


@tool
async def fetch_url_content(
    url: str,
) -> dict:
    """Fetch and extract main content from a URL.

    Use this to get the full text content of a web page
    for deeper analysis or extraction.

    Args:
        url: URL to fetch

    Returns:
        Dict with content, title, author, publish_date, word_count, content_hash
    """
    service = get_web_fetch_service()
    result = await service.fetch(url, extract_main_content=True)

    return {
        "url": result.url,
        "title": result.title,
        "author": result.author,
        "content": result.content,
        "publish_date": result.publish_date.isoformat() if result.publish_date else None,
        "word_count": result.word_count,
        "content_hash": result.content_hash,
    }


@tool
async def search_academic_papers(
    query: str,
    year_start: int | None = None,
    year_end: int | None = None,
    limit: int = 10,
) -> list[dict]:
    """Search for academic papers on Semantic Scholar.

    Use this to find peer-reviewed research papers for
    authoritative sources on academic topics.

    Args:
        query: Search query for academic papers
        year_start: Only papers published after this year
        year_end: Only papers published before this year
        limit: Maximum number of results (default 10)

    Returns:
        List of papers with title, authors, abstract, year, citation_count, url
    """
    import httpx

    api_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": min(limit, 20),
        "fields": "title,authors,abstract,year,citationCount,url,openAccessPdf",
    }

    if year_start:
        params["year"] = f"{year_start}-"
    if year_end:
        if "year" in params:
            params["year"] = f"{year_start}-{year_end}"
        else:
            params["year"] = f"-{year_end}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

        results = []
        for paper in data.get("data", []):
            authors = [a.get("name", "") for a in paper.get("authors", [])]
            results.append(
                {
                    "title": paper.get("title", ""),
                    "authors": authors,
                    "abstract": paper.get("abstract", ""),
                    "year": paper.get("year"),
                    "citation_count": paper.get("citationCount", 0),
                    "url": paper.get("url", ""),
                    "pdf_url": paper.get("openAccessPdf", {}).get("url"),
                }
            )

        logger.info(f"Academic search for '{query}' returned {len(results)} papers")
        return results

    except Exception as e:
        logger.error(f"Academic search failed for '{query}': {e}")
        return []


@tool
async def search_with_domain_filter(
    query: str,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Search the web with domain filtering.

    Use this when you want to search specific sites or exclude
    certain domains from results.

    Args:
        query: Search query
        include_domains: Only include results from these domains (e.g., ["nature.com", "sciencedirect.com"])
        exclude_domains: Exclude results from these domains (e.g., ["wikipedia.org"])
        max_results: Maximum results (default 10)

    Returns:
        List of filtered search results
    """
    service = get_web_search_service()
    results = await service.search(
        query=query,
        max_results=max_results,
        include_domains=include_domains,
        exclude_domains=exclude_domains,
    )

    return [
        {
            "url": r.url,
            "title": r.title,
            "snippet": r.snippet,
            "score": r.score,
        }
        for r in results
    ]
