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

CREDIBILITY_THRESHOLD = 0.6

# Target sources per depth - NOT forced minimums, just targets for replan to consider
DEPTH_TARGETS = {
    "overview": 5,
    "standard": 10,
    "deep": 20,
    "exhaustive": 35,
}

MAX_SOURCES = 150


def calculate_source_target(
    target_word_count: int,
    depth: str,
) -> int:
    """Calculate target source count based on content requirements.

    This is a TARGET, not a minimum - we never force bad sources.
    If we don't meet the target, replan can trigger more research.

    Args:
        target_word_count: Target word count for the content
        depth: Depth level (overview, standard, deep, exhaustive)

    Returns:
        Target source count (not enforced, just advisory)
    """
    # Base: ~1.5 sources per 2000 words
    word_based = int((target_word_count / 2000) * 1.5)

    # Depth target
    depth_target = DEPTH_TARGETS.get(depth, 10)

    # Use higher of word-based or depth target
    return max(word_based, depth_target)


async def verify_node(state: ContentGenerationState) -> dict:
    """Verify source candidates and produce approved sources.

    This node:
    1. Evaluates ALL candidates (scores each one)
    2. Keeps all that pass the threshold (quality-based, not count-based)
    3. Sorts by score, caps at MAX_SOURCES
    4. Reports if below target so replan can trigger more research

    Args:
        state: Current workflow state

    Returns:
        Dict with approved_sources and source_shortage flag
    """
    target_word_count = state.get("target_word_count", 50000)
    depth = state.get("depth", "standard")

    source_target = calculate_source_target(
        target_word_count=target_word_count,
        depth=depth,
    )

    candidates = state.get("source_candidates", [])
    existing_approved = {s.candidate_id for s in state.get("approved_sources", [])}

    candidates_to_verify = [
        c for c in candidates if c.id not in existing_approved
    ]

    logger.info(
        f"Verify node starting with {len(candidates_to_verify)} candidates. "
        f"Target: {source_target} sources (depth={depth})"
    )

    if not candidates_to_verify:
        logger.info("No new candidates to verify")
        return {
            "current_phase": "extract",
            "verification_complete": True,
            "messages": [AIMessage(content="No new sources to verify.")],
        }

    # Score ALL candidates - collect (candidate, score, credibility_result) tuples
    scored_candidates = []
    rejected_count = 0

    logger.info(f"Scoring all {len(candidates_to_verify)} candidates...")

    for idx, candidate in enumerate(candidates_to_verify):
        if idx > 0 and idx % 50 == 0:
            logger.info(f"  Progress: {idx}/{len(candidates_to_verify)} candidates scored")

        try:
            credibility_result = await assess_source_credibility.ainvoke({
                "url": candidate.url,
                "title": candidate.title,
                "snippet": candidate.snippet,
            })

            if credibility_result["recommendation"] == "reject":
                rejected_count += 1
                continue

            credibility_score = credibility_result["credibility_score"]
            if credibility_score < CREDIBILITY_THRESHOLD:
                rejected_count += 1
                continue

            # Passed threshold - add to scored list
            scored_candidates.append((candidate, credibility_score, credibility_result))

        except Exception as e:
            logger.warning(f"Error scoring {candidate.url}: {e}")
            continue

    logger.info(
        f"Scoring complete: {len(scored_candidates)} passed threshold, "
        f"{rejected_count} rejected"
    )

    # Sort by score (highest first) and cap at MAX_SOURCES
    scored_candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = scored_candidates[:MAX_SOURCES]

    logger.info(f"Keeping top {len(top_candidates)} sources (max={MAX_SOURCES})")

    # Now fetch content and create ApprovedSource for each
    approved_sources = []

    for candidate, credibility_score, credibility_result in top_candidates:
        try:
            content = None
            content_hash = ""
            publish_date = None
            fetch_result = {}

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
                        logger.info(f"Stale source skipped: {candidate.url}")
                        continue

            except Exception as e:
                logger.warning(f"Could not fetch content from {candidate.url}: {e}")
                continue

            # Only approve sources with actual fetchable content
            if not content or not content.strip():
                logger.info(f"No content fetched, skipping: {candidate.url}")
                continue

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
                topics_covered=candidate.metadata.get("topics", []) if candidate.metadata else [],
                verification_notes="; ".join(credibility_result.get("strengths", [])),
            )
            approved_sources.append(approved)

        except Exception as e:
            logger.error(f"Error processing approved source {candidate.url}: {e}")
            continue

    # Check if we're below target
    source_shortage = len(approved_sources) < source_target
    shortage_amount = source_target - len(approved_sources) if source_shortage else 0

    logger.info(
        f"Verification complete: {len(approved_sources)} approved, {rejected_count} rejected. "
        f"Target: {source_target}. Shortage: {shortage_amount if source_shortage else 'None'}"
    )

    message = f"Verified {len(approved_sources)} sources (target: {source_target})."
    if source_shortage:
        message += f" {shortage_amount} below target - may need more research."

    return {
        "approved_sources": approved_sources,
        "source_shortage": source_shortage,
        "source_shortage_amount": shortage_amount,
        "source_target": source_target,
        "current_phase": "extract",
        "verification_complete": True,
        "messages": [AIMessage(content=message)],
    }
