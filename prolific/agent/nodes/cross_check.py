"""Cross-check node for verifying claims across sources.

The Cross-Check Agent validates claims, identifies conflicts,
and updates confidence levels based on corroboration.

Uses embedding similarity for efficient pre-filtering before LLM verification.
"""

import logging
from collections import defaultdict

import numpy as np
from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.core.config import settings
from prolific.schemas.artifacts import ClaimStatus, ConfidenceLevel
from prolific.services.embedding import get_embedding_service
from prolific.tools.verification_tools import detect_claim_conflicts

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    return float(np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr)))


async def cross_check_node(state: ContentGenerationState) -> dict:
    """Cross-check claims across sources for verification.

    Uses a two-phase approach:
    1. Embed all claims and find similar pairs (cheap, fast)
    2. Only LLM-verify high-similarity pairs from different sources

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

    logger.info(f"Cross-checking {len(claims)} claims using embedding similarity")

    # Phase 1: Embed all claims (single batch API call)
    logger.info("Phase 1: Generating embeddings for all claims...")
    embedding_service = get_embedding_service()
    claim_texts = [c.statement for c in claims]

    try:
        embeddings = await embedding_service.embed_texts(claim_texts)
        logger.info(f"Generated {len(embeddings)} embeddings")
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        # Fallback: mark all as verified without cross-checking
        for claim in claims:
            claim.status = ClaimStatus.VERIFIED
        return {
            "claims": claims,
            "current_phase": "synthesize",
            "messages": [AIMessage(content=f"Cross-check skipped (embedding error): {len(claims)} claims marked verified.")],
        }

    # Phase 2: Find similar pairs from different sources
    logger.info("Phase 2: Finding similar claim pairs...")
    similar_pairs = []  # (idx1, idx2, similarity)

    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            # Skip if from same source
            if set(claims[i].source_ids) & set(claims[j].source_ids):
                continue

            similarity = cosine_similarity(embeddings[i], embeddings[j])

            if similarity >= settings.cross_check_similarity_threshold:
                similar_pairs.append((i, j, similarity))

    # Sort by similarity (highest first) and limit
    similar_pairs.sort(key=lambda x: -x[2])
    pairs_to_check = similar_pairs[:settings.cross_check_max_llm_comparisons]

    logger.info(
        f"Found {len(similar_pairs)} similar pairs (>= {settings.cross_check_similarity_threshold}), "
        f"checking top {len(pairs_to_check)} with LLM"
    )

    # Phase 3: LLM verification of high-similarity pairs
    logger.info("Phase 3: LLM verification of similar pairs...")

    # Track relationships
    corroborations = defaultdict(set)  # claim_idx -> set of corroborating source_ids
    conflicts = defaultdict(list)  # claim_idx -> list of conflicting claim_ids
    conflict_notes = {}  # claim_idx -> conflict description

    for check_idx, (i, j, similarity) in enumerate(pairs_to_check):
        if (check_idx + 1) % 20 == 0:
            logger.info(f"LLM check progress: {check_idx + 1}/{len(pairs_to_check)}")

        claim1, claim2 = claims[i], claims[j]

        # Very high similarity likely means corroboration, not conflict
        if similarity >= settings.cross_check_corroboration_threshold:
            corroborations[i].update(claim2.source_ids)
            corroborations[j].update(claim1.source_ids)
            continue

        # Medium-high similarity needs LLM check
        try:
            source1 = approved_sources.get(claim1.source_ids[0])
            source2 = approved_sources.get(claim2.source_ids[0])

            result = await detect_claim_conflicts.ainvoke({
                "claim1": claim1.statement,
                "claim1_source": source1.title if source1 else "Unknown",
                "claim2": claim2.statement,
                "claim2_source": source2.title if source2 else "Unknown",
            })

            if result.get("has_conflict"):
                if result.get("conflict_type") == "direct":
                    conflicts[i].append(claim2.id)
                    conflicts[j].append(claim1.id)
                    conflict_notes[i] = result.get("conflict_description", "")
                    conflict_notes[j] = result.get("conflict_description", "")
            else:
                # Not a conflict = corroboration
                corroborations[i].update(claim2.source_ids)
                corroborations[j].update(claim1.source_ids)

        except Exception as e:
            logger.warning(f"Conflict detection failed for pair ({i}, {j}): {e}")

    # Phase 4: Update claim statuses
    logger.info("Phase 4: Updating claim statuses...")
    updated_claims = []

    for idx, claim in enumerate(claims):
        claim_copy = claim.model_copy()

        # Update confidence based on corroboration
        corroborating_sources = corroborations.get(idx, set())
        if len(corroborating_sources) >= 2:
            claim_copy.confidence = ConfidenceLevel.HIGH
        elif len(corroborating_sources) >= 1:
            if claim_copy.confidence == ConfidenceLevel.LOW:
                claim_copy.confidence = ConfidenceLevel.MEDIUM

        # Update status based on conflicts
        conflicting = conflicts.get(idx, [])
        if conflicting:
            claim_copy.confidence = ConfidenceLevel.CONFLICT
            claim_copy.conflicting_claim_ids = conflicting
            claim_copy.conflict_notes = conflict_notes.get(idx, "")
            claim_copy.status = ClaimStatus.CONTESTED
        else:
            claim_copy.status = ClaimStatus.VERIFIED

        updated_claims.append(claim_copy)

    # Summary stats
    verified_count = sum(1 for c in updated_claims if c.status == ClaimStatus.VERIFIED)
    contested_count = sum(1 for c in updated_claims if c.status == ClaimStatus.CONTESTED)
    high_confidence = sum(1 for c in updated_claims if c.confidence == ConfidenceLevel.HIGH)

    logger.info(
        f"Cross-check complete: {verified_count} verified, {contested_count} contested, "
        f"{high_confidence} high confidence (corroborated)"
    )

    return {
        "claims": updated_claims,
        "current_phase": "synthesize",
        "messages": [
            AIMessage(
                content=f"Cross-checked {len(updated_claims)} claims. "
                f"{verified_count} verified, {contested_count} contested, "
                f"{high_confidence} corroborated across sources."
            )
        ],
    }
