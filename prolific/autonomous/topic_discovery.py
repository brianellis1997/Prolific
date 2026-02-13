"""Discover trending AI/SWE topics via Tavily web search."""

import asyncio
import logging
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.services.web_search import get_web_search_service

logger = logging.getLogger(__name__)

SEARCH_QUERIES = [
    {
        "query": "latest AI research breakthroughs 2026",
        "include_domains": ["arxiv.org", "openai.com", "anthropic.com", "deepmind.google"],
        "category": "ai_research",
    },
    {
        "query": "new machine learning techniques 2026",
        "include_domains": ["arxiv.org", "paperswithcode.com"],
        "category": "ai_research",
    },
    {
        "query": "large language model developments this week",
        "include_domains": None,
        "category": "ai_research",
    },
    {
        "query": "software engineering best practices trends 2026",
        "include_domains": ["martinfowler.com", "blog.pragmaticengineer.com"],
        "category": "swe_practice",
    },
    {
        "query": "new developer tools frameworks 2026",
        "include_domains": None,
        "category": "swe_practice",
    },
    {
        "query": "software architecture patterns distributed systems 2026",
        "include_domains": None,
        "category": "architecture",
    },
    {
        "query": "cloud infrastructure AI deployment new",
        "include_domains": None,
        "category": "architecture",
    },
    {
        "query": "trending technology hacker news this week AI",
        "include_domains": ["news.ycombinator.com"],
        "category": "industry_news",
    },
    {
        "query": "AI startup product launch 2026",
        "include_domains": ["techcrunch.com", "theverge.com", "arstechnica.com"],
        "category": "industry_news",
    },
]


class TopicCandidate(BaseModel):
    title: str
    description: str
    source_urls: list[str] = Field(default_factory=list)
    source_titles: list[str] = Field(default_factory=list)
    category: str
    freshness_score: float = 0.5
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


class TopicDiscoveryResult(BaseModel):
    candidates: list[TopicCandidate]


CLUSTERING_PROMPT = """You are an editorial researcher for a technical blog focused on AI, software engineering, and system architecture.

Given raw search results from multiple sources, cluster them into 10-15 distinct blog post topic candidates.

For each topic candidate, provide:
- title: A compelling blog post title
- description: 2-3 sentence description of what the post would cover
- source_urls: URLs from the search results that relate to this topic
- source_titles: Titles of those sources
- category: One of "ai_research", "swe_practice", "architecture", "industry_news"
- freshness_score: 0.0-1.0 indicating how recent/trending (1.0 = breaking news today)

Focus on topics that:
1. Are genuinely trending or represent significant developments
2. Have enough depth for a 5000-word technical article
3. Would interest AI/SWE practitioners
4. Are specific enough to write about (not vague like "AI is changing things")

RAW SEARCH RESULTS:
{search_results}"""


async def _run_search(query_config: dict) -> list[dict]:
    search_service = get_web_search_service()
    try:
        results = await search_service.search(
            query=query_config["query"],
            max_results=10,
            search_depth="basic",
            include_domains=query_config.get("include_domains"),
        )
        return [
            {
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "category": query_config["category"],
            }
            for r in results
        ]
    except Exception as e:
        logger.warning(f"Search failed for '{query_config['query']}': {e}")
        return []


async def discover_trending_topics(max_candidates: int = 15) -> list[TopicCandidate]:
    logger.info(f"Running {len(SEARCH_QUERIES)} search queries for topic discovery")

    all_results = await asyncio.gather(
        *[_run_search(q) for q in SEARCH_QUERIES]
    )
    flat_results = [r for batch in all_results for r in batch]
    logger.info(f"Collected {len(flat_results)} total search results")

    if not flat_results:
        logger.warning("No search results found")
        return []

    results_text = "\n".join(
        f"- [{r['title']}]({r['url']}) ({r['category']}): {r['snippet'][:200]}"
        for r in flat_results
    )

    llm_service = get_llm_service()
    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content="You are an editorial researcher."),
            HumanMessage(content=CLUSTERING_PROMPT.format(search_results=results_text)),
        ],
        output_schema=TopicDiscoveryResult,
        tier="research",
        temperature=0.4,
    )

    candidates = result.candidates[:max_candidates]
    logger.info(f"Clustered into {len(candidates)} topic candidates")
    return candidates
