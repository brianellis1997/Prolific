"""Verify node for validating source credibility.

The Verifier Agent evaluates source candidates and
produces ApprovedSource artifacts for credible sources.
"""

import logging
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
MAX_SOURCES_TO_APPROVE = 20


async def verify_node(state: ContentGenerationState) -> dict:
    """Verify source candidates and produce approved sources.

    This node:
    1. Evaluates each candidate's credibility
    2. Checks recency for time-sensitive topics
    3. Fetches content for approved sources
    4. Creates ApprovedSource artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with approved_sources to merge into state
    """
    logger.info(f"Verify node starting with {len(state['source_candidates'])} candidates")

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

    for candidate in candidates_to_verify[:MAX_SOURCES_TO_APPROVE * 2]:
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

            approved = ApprovedSource(
                id=uuid4(),
                candidate_id=candidate.id,
                url=candidate.url,
                title=candidate.title,
                source_type=credibility_result.get("source_type", candidate.source_type),
                author=fetch_result.get("author") if content else None,
                publication_date=None,
                credibility_score=credibility_score,
                content_hash=content_hash,
                full_text=content,
                topics_covered=candidate.metadata.get("topics", []),
                verification_notes="; ".join(credibility_result.get("strengths", [])),
            )
            approved_sources.append(approved)

            if len(approved_sources) >= MAX_SOURCES_TO_APPROVE:
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
