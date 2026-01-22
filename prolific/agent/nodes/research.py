"""Research node for discovering and gathering source material.

The Research Agent searches for relevant sources on the topic
and subtopics, creating SourceCandidate artifacts.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import SourceCandidate
from prolific.services.llm import get_llm_service
from prolific.tools.research_tools import (
    fetch_url_content,
    search_academic_papers,
    web_search,
)

logger = logging.getLogger(__name__)

RESEARCH_SYSTEM_PROMPT = """You are a research agent tasked with finding high-quality sources on a topic.

Your goal is to find diverse, credible sources that cover the topic thoroughly.

Topic: {topic}
Subtopics to cover: {subtopics}
Focus areas: {focus_areas}
Depth level: {depth}

Current gaps to address (if any):
{gaps}

Guidelines:
1. Search for a mix of source types (academic, news, official, expert blogs)
2. Prioritize authoritative and recent sources
3. Look for diverse perspectives on the topic
4. For academic topics, include peer-reviewed research
5. Generate multiple search queries to cover different angles

For each source found, assess its relevance (0-1) to the topic."""


async def research_node(state: ContentGenerationState) -> dict:
    """Execute research to find source candidates.

    This node:
    1. Analyzes the topic and subtopics
    2. Generates search queries
    3. Executes web and academic searches
    4. Creates SourceCandidate artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with source_candidates to merge into state
    """
    logger.info(f"Research node starting for topic: {state['topic']}")

    llm_service = get_llm_service()
    llm = llm_service.get_llm("research", temperature=0.7)

    gaps_text = "None - initial research"
    if state.get("content_gaps"):
        gaps_text = "\n".join(
            f"- {gap.description} (priority: {gap.priority})"
            for gap in state["content_gaps"]
            if not gap.resolved
        )

    system_message = SystemMessage(
        content=RESEARCH_SYSTEM_PROMPT.format(
            topic=state["topic"],
            subtopics=", ".join(state.get("subtopics", [])),
            focus_areas=", ".join(state.get("focus_areas", [])),
            depth=state.get("depth", "standard"),
            gaps=gaps_text,
        )
    )

    query_prompt = HumanMessage(
        content="""Generate 5-8 search queries to find comprehensive sources on this topic.

Return queries as a simple list, one per line. Include:
- General topic queries
- Specific subtopic queries
- Academic/research queries
- Recent news/developments queries"""
    )

    response = await llm.ainvoke([system_message, query_prompt])
    queries = [q.strip() for q in response.content.split("\n") if q.strip()][:8]

    logger.info(f"Generated {len(queries)} search queries")

    source_candidates = []

    for query in queries:
        try:
            results = await web_search.ainvoke(
                {"query": query, "max_results": 5, "search_depth": "basic"}
            )

            for result in results:
                source_type = "website"
                url = result.get("url", "")

                if "arxiv.org" in url or "doi.org" in url:
                    source_type = "academic"
                elif any(
                    d in url
                    for d in ["nytimes.com", "bbc.com", "reuters.com", "wsj.com"]
                ):
                    source_type = "news"

                candidate = SourceCandidate(
                    id=uuid4(),
                    url=url,
                    title=result.get("title", ""),
                    source_type=source_type,
                    snippet=result.get("snippet", ""),
                    relevance_score=result.get("score", 0.5),
                    query_context=query,
                )
                source_candidates.append(candidate)

        except Exception as e:
            logger.warning(f"Search failed for query '{query}': {e}")

    if state.get("depth") in ["deep", "exhaustive"]:
        academic_query = f"{state['topic']} research"
        try:
            papers = await search_academic_papers.ainvoke(
                {"query": academic_query, "limit": 10}
            )

            for paper in papers:
                if paper.get("url"):
                    candidate = SourceCandidate(
                        id=uuid4(),
                        url=paper.get("url", ""),
                        title=paper.get("title", ""),
                        source_type="academic",
                        snippet=paper.get("abstract", "")[:500],
                        relevance_score=0.8,
                        query_context=f"Academic: {academic_query}",
                        metadata={
                            "authors": paper.get("authors", []),
                            "year": paper.get("year"),
                            "citation_count": paper.get("citation_count", 0),
                        },
                    )
                    source_candidates.append(candidate)

        except Exception as e:
            logger.warning(f"Academic search failed: {e}")

    seen_urls = set()
    unique_candidates = []
    for candidate in source_candidates:
        if candidate.url not in seen_urls:
            seen_urls.add(candidate.url)
            unique_candidates.append(candidate)

    logger.info(f"Research complete: {len(unique_candidates)} unique candidates found")

    return {
        "source_candidates": unique_candidates,
        "current_phase": "verify",
        "messages": [
            AIMessage(
                content=f"Research complete. Found {len(unique_candidates)} source candidates."
            )
        ],
    }
