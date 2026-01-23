"""Verify node for validating source credibility.

The Verifier Agent evaluates source candidates and
produces ApprovedSource artifacts for credible sources.
"""

import logging
from datetime import datetime
from uuid import uuid4

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ApprovedSource, SourceCandidate
from prolific.tools.research_tools import fetch_url_content
from prolific.tools.verification_tools import (
    assess_source_credibility,
    check_source_recency,
)

logger = logging.getLogger(__name__)

CREDIBILITY_THRESHOLD = 0.5

DEPTH_MULTIPLIERS = {
    "overview": 0.5,
    "standard": 1.0,
    "deep": 1.5,
    "exhaustive": 2.0,
}

MIN_SOURCES = 10
MAX_SOURCES = 150
SOURCES_PER_2K_WORDS = 1
SOURCES_PER_REPLAN = 10


def calculate_dynamic_source_limit(
    target_word_count: int,
    depth: str,
    iteration_count: int = 0,
) -> int:
    """Calculate dynamic source limit based on content requirements.

    The limit scales with:
    - Target word count: ~1 source per 2000 words
    - Depth level: multiplier for deeper research
    - Iteration count: additional sources allowed per replan cycle

    Args:
        target_word_count: Target word count for the content
        depth: Depth level (overview, standard, deep, exhaustive)
        iteration_count: Current iteration number (allows expansion on replan)

    Returns:
        Dynamic source limit between MIN_SOURCES and MAX_SOURCES
    """
    base_sources = target_word_count // 2000 * SOURCES_PER_2K_WORDS

    depth_multiplier = DEPTH_MULTIPLIERS.get(depth, 1.0)
    scaled_sources = int(base_sources * depth_multiplier)

    replan_bonus = iteration_count * SOURCES_PER_REPLAN

    total = scaled_sources + replan_bonus

    return max(MIN_SOURCES, min(total, MAX_SOURCES))


async def verify_node(state: ContentGenerationState) -> dict:
    """Verify source candidates and produce approved sources.

    This node:
    1. Evaluates each candidate's credibility
    2. Checks recency for time-sensitive topics
    3. Fetches content for approved sources
    4. Creates ApprovedSource artifacts

    Source limit is dynamically calculated based on:
    - target_word_count: More words = more sources needed
    - depth: Deeper research = more sources
    - iteration_count: Replan cycles can expand the limit

    Args:
        state: Current workflow state

    Returns:
        Dict with approved_sources to merge into state
    """
    target_word_count = state.get("target_word_count", 50000)
    depth = state.get("depth", "standard")
    iteration_count = state.get("iteration_count", 0)

    source_limit = calculate_dynamic_source_limit(
        target_word_count=target_word_count,
        depth=depth,
        iteration_count=iteration_count,
    )

    logger.info(
        f"Verify node starting with {len(state['source_candidates'])} candidates. "
        f"Dynamic source limit: {source_limit} (words={target_word_count}, depth={depth}, iter={iteration_count})"
    )

    candidates = state.get("source_candidates", [])
    existing_approved = {s.candidate_id for s in state.get("approved_sources", [])}

    candidates_to_verify = [
        c for c in candidates if c.id not in existing_approved
    ]

    if not candidates_to_verify:
        logger.info("No new candidates to verify")
        return {
            "current_phase": "extract",
            "verification_complete": True,
            "messages": [AIMessage(content="No new sources to verify.")],
        }

    approved_sources = []
    rejected_count = 0

    for candidate in candidates_to_verify[:source_limit * 2]:
        try:
            credibility_result = await assess_source_credibility.ainvoke({
                "url": candidate.url,
                "title": candidate.title,
                "snippet": candidate.snippet,
            })

            if credibility_result["recommendation"] == "reject":
                logger.info(f"Rejected source: {candidate.url} - {credibility_result['concerns']}")
                rejected_count += 1
                continue

            credibility_score = credibility_result["credibility_score"]
            if credibility_score < CREDIBILITY_THRESHOLD:
                logger.info(f"Low credibility ({credibility_score}): {candidate.url}")
                rejected_count += 1
                continue

            content = None
            content_hash = ""
            try:
                fetch_result = await fetch_url_content.ainvoke({"url": candidate.url})
                content = fetch_result.get("content", "")
                content_hash = fetch_result.get("content_hash", "")
                publish_date = fetch_result.get("publish_date")

                if publish_date:
                    recency_result = await check_source_recency.ainvoke({
                        "publish_date": publish_date,
                        "topic": state["topic"],
                    })
                    if recency_result.get("staleness_risk") == "high":
                        logger.info(f"Stale source: {candidate.url}")
                        continue

            except Exception as e:
                logger.warning(f"Could not fetch content from {candidate.url}: {e}")

            source_type = credibility_result.get("source_type", candidate.source_type)
            if source_type == "unknown" or source_type not in ["academic", "news", "book", "website", "primary"]:
                source_type = "website"

            author = None
            publication_date = None

            if source_type == "academic" and candidate.metadata:
                authors = candidate.metadata.get("authors", [])
                if authors:
                    if len(authors) == 1:
                        author = authors[0]
                    elif len(authors) == 2:
                        author = f"{authors[0]} & {authors[1]}"
                    else:
                        author = f"{authors[0]} et al."

                year = candidate.metadata.get("year")
                if year:
                    try:
                        publication_date = datetime(int(year), 1, 1)
                    except (ValueError, TypeError):
                        pass

            if not author and content:
                author = fetch_result.get("author")
            if not publication_date and publish_date:
                publication_date = publish_date

            approved = ApprovedSource(
                id=uuid4(),
                candidate_id=candidate.id,
                url=candidate.url,
                title=candidate.title,
                source_type=source_type,
                author=author,
                publication_date=publication_date,
                credibility_score=credibility_score,
                content_hash=content_hash,
                full_text=content,
                topics_covered=candidate.metadata.get("topics", []),
                verification_notes="; ".join(credibility_result.get("strengths", [])),
            )
            approved_sources.append(approved)

            if len(approved_sources) >= source_limit:
                logger.info(f"Reached dynamic source limit of {source_limit}")
                break

        except Exception as e:
            logger.error(f"Error verifying {candidate.url}: {e}")
            continue

    logger.info(
        f"Verification complete: {len(approved_sources)} approved, {rejected_count} rejected"
    )

    return {
        "approved_sources": approved_sources,
        "current_phase": "extract",
        "verification_complete": True,
        "messages": [
            AIMessage(
                content=f"Verified {len(approved_sources)} sources. {rejected_count} rejected."
            )
        ],
    }
