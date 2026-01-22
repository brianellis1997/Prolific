"""Integrate node for merging and checking content consistency.

The Integrator Agent merges draft chunks, checks for consistency,
and ensures the final content is coherent and non-repetitive.
"""

import logging

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.services.embedding import get_embedding_service
from prolific.rag.deduplication import DeduplicationGate
from prolific.rag.indexes import MultiIndexRAG
from prolific.tools.writing_tools import (
    analyze_chapter_transition,
    check_internal_consistency,
    check_style_compliance,
)

logger = logging.getLogger(__name__)


async def integrate_node(state: ContentGenerationState) -> dict:
    """Integrate and check consistency of draft content.

    This node:
    1. Checks for repetition across chapters (de-duplication)
    2. Verifies style consistency
    3. Analyzes chapter transitions
    4. Identifies internal contradictions

    Args:
        state: Current workflow state

    Returns:
        Dict with updated draft_chunks, warnings, and phase info
    """
    logger.info("=== INTEGRATION PHASE ===")

    draft_chunks = state.get("draft_chunks", [])
    global_memory = state.get("global_memory")
    chapter_briefs = {b.chapter_id: b for b in state.get("chapter_briefs", [])}

    if not draft_chunks:
        logger.info("No draft chunks to integrate")
        return {
            "current_phase": "replan",
            "integration_complete": True,
            "messages": [AIMessage(content="No content to integrate.")],
        }

    sorted_chunks = sorted(
        draft_chunks,
        key=lambda c: chapter_briefs.get(c.chapter_id, type("", (), {"chapter_number": 0})).chapter_number
    )

    logger.info(f"Chapters to integrate: {len(sorted_chunks)}")
    logger.info(f"Expected LLM calls: ~{len(sorted_chunks) * 2 + len(sorted_chunks) - 1 + 1} (dedup + style per chapter, transitions, consistency)")

    warnings = []
    updated_chunks = []

    style_guide = global_memory.style_guide if global_memory else None

    try:
        rag = MultiIndexRAG()
        embedding_service = get_embedding_service()
        dedup_gate = DeduplicationGate(rag)
        use_dedup = True
    except Exception as e:
        logger.warning(f"Could not initialize deduplication: {e}")
        use_dedup = False

    for chunk_idx, chunk in enumerate(sorted_chunks, 1):
        brief = chapter_briefs.get(chunk.chapter_id)
        chapter_num = brief.chapter_number if brief else "?"
        logger.info(f"[{chunk_idx}/{len(sorted_chunks)}] Processing chapter {chapter_num}")

        chunk_copy = chunk.model_copy()

        if use_dedup:
            try:
                chunk_embedding = await embedding_service.embed_text(chunk.content[:2000])
                dedup_result = await dedup_gate.check_chunk(
                    chunk_embedding=chunk_embedding,
                    chapter_id=str(chunk.chapter_id),
                )

                if not dedup_result.is_acceptable:
                    warnings.append(
                        f"Chapter {chapter_briefs.get(chunk.chapter_id, type('', (), {'chapter_number': '?'})).chapter_number}: "
                        f"{dedup_result.rejection_reason}"
                    )
                    chunk_copy.repetition_score = dedup_result.similarity_score

                warnings.extend(dedup_result.warnings)

            except Exception as e:
                logger.warning(f"Deduplication check failed: {e}")

        if style_guide:
            try:
                style_result = await check_style_compliance.ainvoke({
                    "content": chunk.content[:3000],
                    "style_tone": style_guide.tone,
                    "formality_level": style_guide.formality_level,
                    "use_contractions": style_guide.use_contractions,
                })

                chunk_copy.style_compliance_score = style_result.get("compliance_score", 0.8)

                if style_result.get("issues"):
                    brief = chapter_briefs.get(chunk.chapter_id)
                    chapter_num = brief.chapter_number if brief else "?"
                    for issue in style_result["issues"][:2]:
                        warnings.append(f"Chapter {chapter_num} style: {issue}")

            except Exception as e:
                logger.warning(f"Style check failed: {e}")

        updated_chunks.append(chunk_copy)

    for i in range(1, len(sorted_chunks)):
        try:
            prev_chunk = sorted_chunks[i - 1]
            curr_chunk = sorted_chunks[i]

            transition_result = await analyze_chapter_transition.ainvoke({
                "previous_chapter_ending": prev_chunk.content[-1500:],
                "current_chapter_beginning": curr_chunk.content[:1500],
            })

            if not transition_result.get("flows_well"):
                prev_brief = chapter_briefs.get(prev_chunk.chapter_id)
                curr_brief = chapter_briefs.get(curr_chunk.chapter_id)
                prev_num = prev_brief.chapter_number if prev_brief else "?"
                curr_num = curr_brief.chapter_number if curr_brief else "?"

                warnings.append(
                    f"Transition issue between chapters {prev_num} and {curr_num}: "
                    f"{transition_result.get('issues', ['Poor flow'])[0]}"
                )

        except Exception as e:
            logger.warning(f"Transition analysis failed: {e}")

    if len(sorted_chunks) > 1:
        try:
            all_content = "\n\n---\n\n".join(
                chunk.content[:2000] for chunk in sorted_chunks[:5]
            )

            glossary_terms = None
            if global_memory and global_memory.glossary:
                glossary_terms = {
                    term: entry.definition
                    for term, entry in list(global_memory.glossary.items())[:20]
                }

            consistency_result = await check_internal_consistency.ainvoke({
                "content": all_content,
                "glossary_terms": glossary_terms,
            })

            if not consistency_result.get("is_consistent"):
                warnings.extend(
                    f"Consistency: {issue}"
                    for issue in consistency_result.get("contradictions", [])[:3]
                )

        except Exception as e:
            logger.warning(f"Consistency check failed: {e}")

    high_repetition = any(c.repetition_score > 0.7 for c in updated_chunks)
    style_issues = any(c.style_compliance_score < 0.6 for c in updated_chunks)

    logger.info(
        f"Integration complete. {len(warnings)} warnings. "
        f"High repetition: {high_repetition}, Style issues: {style_issues}"
    )

    return {
        "draft_chunks": updated_chunks,
        "warnings": warnings,
        "current_phase": "replan",
        "integration_complete": True,
        "messages": [
            AIMessage(
                content=f"Integration complete. {len(warnings)} issues found."
            )
        ],
    }
