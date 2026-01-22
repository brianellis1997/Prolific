"""Extract node for deep reading and claim extraction.

The Extractor Agent thoroughly analyzes approved sources
and extracts claims, evidence, and structured data.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import Claim, ClaimStatus, ConfidenceLevel, EvidenceSnippet
from prolific.tools.extraction_tools import (
    extract_claims_from_text,
    extract_key_quotes,
    extract_statistics,
)

logger = logging.getLogger(__name__)


async def extract_node(state: ContentGenerationState) -> dict:
    """Extract claims and evidence from approved sources.

    This node (runs in parallel for each source):
    1. Deep reads the source content
    2. Extracts factual claims
    3. Extracts supporting evidence/quotes
    4. Extracts statistics and data
    5. Creates Claim and EvidenceSnippet artifacts

    Args:
        state: Current workflow state (may contain single source for parallel)

    Returns:
        Dict with claims and evidence_snippets to merge into state
    """
    approved_sources = state.get("approved_sources", [])
    existing_claim_sources = {
        source_id
        for claim in state.get("claims", [])
        for source_id in claim.source_ids
    }

    sources_to_extract = [
        s for s in approved_sources
        if s.id not in existing_claim_sources and s.full_text
    ]

    if not sources_to_extract:
        logger.info("No sources to extract from")
        return {
            "current_phase": "cross_check",
            "extraction_complete": True,
            "messages": [AIMessage(content="No new sources to extract from.")],
        }

    logger.info(f"Extracting from {len(sources_to_extract)} sources")

    all_claims = []
    all_evidence = []

    for source in sources_to_extract:
        try:
            logger.info(f"Extracting from: {source.title}")

            claims_result = await extract_claims_from_text.ainvoke({
                "text": source.full_text,
                "topic_focus": state.get("subtopics", [state["topic"]]),
                "max_claims": 15,
            })

            for claim_data in claims_result:
                evidence = EvidenceSnippet(
                    id=uuid4(),
                    source_id=source.id,
                    text=claim_data.get("evidence_quote", ""),
                    is_direct_quote=True,
                )
                all_evidence.append(evidence)

                confidence = ConfidenceLevel.MEDIUM
                if claim_data.get("confidence") == "high":
                    confidence = ConfidenceLevel.HIGH
                elif claim_data.get("confidence") == "low":
                    confidence = ConfidenceLevel.LOW

                claim = Claim(
                    id=uuid4(),
                    statement=claim_data.get("statement", ""),
                    evidence_ids=[evidence.id],
                    source_ids=[source.id],
                    confidence=confidence,
                    status=ClaimStatus.PENDING,
                    topic_tags=claim_data.get("topic_tags", []),
                )
                all_claims.append(claim)

            quotes_result = await extract_key_quotes.ainvoke({
                "text": source.full_text,
                "topic": state["topic"],
                "max_quotes": 5,
            })

            for quote_data in quotes_result:
                evidence = EvidenceSnippet(
                    id=uuid4(),
                    source_id=source.id,
                    text=quote_data.get("text", ""),
                    context=quote_data.get("relevance", ""),
                    is_direct_quote=True,
                )
                all_evidence.append(evidence)

            stats_result = await extract_statistics.ainvoke({
                "text": source.full_text,
            })

            for stat_data in stats_result:
                evidence = EvidenceSnippet(
                    id=uuid4(),
                    source_id=source.id,
                    text=f"{stat_data.get('value', '')}: {stat_data.get('description', '')}",
                    context=stat_data.get("context", ""),
                    is_direct_quote=False,
                )
                all_evidence.append(evidence)

                claim = Claim(
                    id=uuid4(),
                    statement=f"{stat_data.get('description', '')}: {stat_data.get('value', '')}",
                    evidence_ids=[evidence.id],
                    source_ids=[source.id],
                    confidence=ConfidenceLevel.HIGH,
                    status=ClaimStatus.PENDING,
                    topic_tags=["statistic", "data"],
                )
                all_claims.append(claim)

        except Exception as e:
            logger.error(f"Extraction failed for {source.title}: {e}")
            continue

    logger.info(f"Extraction complete: {len(all_claims)} claims, {len(all_evidence)} evidence pieces")

    return {
        "claims": all_claims,
        "evidence_snippets": all_evidence,
        "current_phase": "cross_check",
        "extraction_complete": True,
        "messages": [
            AIMessage(
                content=f"Extracted {len(all_claims)} claims and {len(all_evidence)} evidence pieces."
            )
        ],
    }
