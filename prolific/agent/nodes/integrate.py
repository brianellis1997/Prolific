"""Integrate node for merging and checking content consistency.

The Integrator Agent merges draft chunks, checks for consistency,
ensures the final content is coherent and non-repetitive, and
embeds visual assets into the content.
"""

import logging

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import VisualAsset, VisualIntent
from prolific.services.embedding import get_embedding_service
from prolific.rag.deduplication import DeduplicationGate
from prolific.rag.indexes import MultiIndexRAG
from prolific.tools.writing_tools import (
    analyze_chapter_transition,
    check_internal_consistency,
    check_style_compliance,
)

logger = logging.getLogger(__name__)


def embed_visuals_in_chapter(
    chapter_content: str,
    chapter_id: str,
    visual_intents: list[VisualIntent],
    visual_assets: list[VisualAsset],
) -> tuple[str, int]:
    """Embed visual assets into chapter content.

    Maps visual assets back to their intents and chapter, then inserts
    markdown image syntax at appropriate locations.

    Args:
        chapter_content: The chapter text content
        chapter_id: UUID of the chapter
        visual_intents: All visual intents from state
        visual_assets: All visual assets from state

    Returns:
        Tuple of (updated content with images, number of images embedded)
    """
    intents_for_chapter = [
        intent for intent in visual_intents
        if str(intent.chapter_id) == str(chapter_id)
    ]

    if not intents_for_chapter:
        return chapter_content, 0

    assets_by_intent = {str(a.intent_id): a for a in visual_assets}

    images_to_embed = []
    for intent in intents_for_chapter:
        asset = assets_by_intent.get(str(intent.id))
        if asset:
            images_to_embed.append((intent, asset))

    if not images_to_embed:
        return chapter_content, 0

    image_blocks = []
    for intent, asset in images_to_embed:
        if asset.base64_data:
            mime = f"image/{asset.format}" if asset.format != "jpg" else "image/jpeg"
            image_url = f"data:{mime};base64,{asset.base64_data}"
        elif asset.url:
            image_url = asset.url
        elif asset.file_path:
            image_url = asset.file_path
        else:
            continue

        alt_text = asset.alt_text or intent.description or "Image"
        caption = asset.caption or ""

        if caption:
            image_md = f'\n\n![{alt_text}]({image_url})\n\n*{caption}*\n'
        else:
            image_md = f'\n\n![{alt_text}]({image_url})\n'

        image_blocks.append(image_md)

    if image_blocks:
        images_section = "\n".join(image_blocks)
        updated_content = chapter_content + images_section
        return updated_content, len(image_blocks)

    return chapter_content, 0


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
    approved_sources = state.get("approved_sources", [])
    visual_intents = state.get("visual_intents", [])
    visual_assets = state.get("visual_assets", [])

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
                    chunk_content=chunk.content,
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

    total_visuals_embedded = 0
    if visual_assets:
        logger.info(f"Embedding {len(visual_assets)} visual assets into chapters")
        chunks_with_visuals = []
        for chunk in updated_chunks:
            updated_content, num_embedded = embed_visuals_in_chapter(
                chapter_content=chunk.content,
                chapter_id=str(chunk.chapter_id),
                visual_intents=visual_intents,
                visual_assets=visual_assets,
            )
            if num_embedded > 0:
                chunk_with_visuals = chunk.model_copy()
                chunk_with_visuals.content = updated_content
                chunk_with_visuals.word_count = len(updated_content.split())
                chunks_with_visuals.append(chunk_with_visuals)
                total_visuals_embedded += num_embedded
            else:
                chunks_with_visuals.append(chunk)
        updated_chunks = chunks_with_visuals
        logger.info(f"Embedded {total_visuals_embedded} visuals across chapters")

    high_repetition = any(c.repetition_score > 0.7 for c in updated_chunks)
    style_issues = any(c.style_compliance_score < 0.6 for c in updated_chunks)

    # Compile references section
    references_lines = []
    for idx, source in enumerate(approved_sources, 1):
        # Format: [N] Author (Year). Title. URL
        author = source.author or "Unknown"
        year = source.publication_date.year if source.publication_date else "n.d."
        title = source.title
        url = source.url

        ref_line = f"[{idx}] {author} ({year}). {title}. {url}"
        references_lines.append(ref_line)

    references_section = ""
    if references_lines:
        references_section = "\n\n---\n\n## References\n\n" + "\n\n".join(references_lines)
        logger.info(f"Compiled {len(references_lines)} references")

    # Store references in global_memory for final output
    if global_memory and references_section:
        global_memory.references_section = references_section

    logger.info(
        f"Integration complete. {len(warnings)} warnings. "
        f"High repetition: {high_repetition}, Style issues: {style_issues}. "
        f"Visuals embedded: {total_visuals_embedded}"
    )

    return {
        "draft_chunks": updated_chunks,
        "global_memory": global_memory,
        "warnings": warnings,
        "current_phase": "replan",
        "integration_complete": True,
        "messages": [
            AIMessage(
                content=f"Integration complete. {len(warnings)} issues found. "
                f"{len(references_lines)} references compiled. {total_visuals_embedded} visuals embedded."
            )
        ],
    }
