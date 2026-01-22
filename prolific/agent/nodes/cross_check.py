"""Cross-check node for verifying claims across sources.

The Cross-Check Agent validates claims, identifies conflicts,
and updates confidence levels based on corroboration.
"""

import logging
from collections import defaultdict

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ClaimStatus, ConfidenceLevel
from prolific.tools.verification_tools import detect_claim_conflicts

logger = logging.getLogger(__name__)


async def cross_check_node(state: ContentGenerationState) -> dict:
    """Cross-check claims across sources for verification.

    This node:
    1. Groups similar claims together
    2. Identifies corroborating claims (increases confidence)
    3. Detects conflicting claims
    4. Updates claim statuses

    Args:
        state: Current workflow state

    Returns:
        Dict with updated claims to merge into state
    """
    claims = list(state.get("claims", []))
    approved_sources = {s.id: s for s in state.get("approved_sources", [])}

    if not claims:
        logger.info("No claims to cross-check")
        return {
            "current_phase": "synthesize",
            "messages": [AIMessage(content="No claims to cross-check.")],
        }

    logger.info(f"Cross-checking {len(claims)} claims")

    topic_groups = defaultdict(list)
    for i, claim in enumerate(claims):
        for tag in claim.topic_tags:
            topic_groups[tag].append(i)

    updated_claims = []
    checked_pairs = set()

    for claim_idx, claim in enumerate(claims):
        claim_copy = claim.model_copy()

        related_indices = set()
        for tag in claim.topic_tags:
            related_indices.update(topic_groups.get(tag, []))

        corroborating_sources = set()
        conflicting_claims = []

        for other_idx in related_indices:
            if other_idx == claim_idx:
                continue

            pair_key = tuple(sorted([claim_idx, other_idx]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            other_claim = claims[other_idx]

            if set(claim.source_ids) & set(other_claim.source_ids):
                continue

            try:
                source1 = approved_sources.get(claim.source_ids[0])
                source2 = approved_sources.get(other_claim.source_ids[0])

                conflict_result = await detect_claim_conflicts.ainvoke({
                    "claim1": claim.statement,
                    "claim1_source": source1.title if source1 else "Unknown",
                    "claim2": other_claim.statement,
                    "claim2_source": source2.title if source2 else "Unknown",
                })

                if conflict_result.get("has_conflict"):
                    if conflict_result.get("conflict_type") == "direct":
                        conflicting_claims.append(other_claim.id)
                        claim_copy.conflict_notes = conflict_result.get(
                            "conflict_description", ""
                        )
                else:
                    similarity_keywords = set(claim.statement.lower().split()) & set(
                        other_claim.statement.lower().split()
                    )
                    if len(similarity_keywords) >= 3:
                        corroborating_sources.update(other_claim.source_ids)

            except Exception as e:
                logger.warning(f"Conflict detection failed: {e}")

        if corroborating_sources:
            if len(corroborating_sources) >= 2:
                claim_copy.confidence = ConfidenceLevel.HIGH
            elif len(corroborating_sources) >= 1:
                if claim_copy.confidence == ConfidenceLevel.LOW:
                    claim_copy.confidence = ConfidenceLevel.MEDIUM

        if conflicting_claims:
            claim_copy.confidence = ConfidenceLevel.CONFLICT
            claim_copy.conflicting_claim_ids = conflicting_claims
            claim_copy.status = ClaimStatus.CONTESTED
        else:
            claim_copy.status = ClaimStatus.VERIFIED

        updated_claims.append(claim_copy)

    verified_count = sum(1 for c in updated_claims if c.status == ClaimStatus.VERIFIED)
    contested_count = sum(1 for c in updated_claims if c.status == ClaimStatus.CONTESTED)
    high_confidence = sum(
        1 for c in updated_claims if c.confidence == ConfidenceLevel.HIGH
    )

    logger.info(
        f"Cross-check complete: {verified_count} verified, {contested_count} contested, "
        f"{high_confidence} high confidence"
    )

    return {
        "claims": updated_claims,
        "current_phase": "synthesize",
        "messages": [
            AIMessage(
                content=f"Cross-checked {len(updated_claims)} claims. "
                f"{verified_count} verified, {contested_count} contested."
            )
        ],
    }
