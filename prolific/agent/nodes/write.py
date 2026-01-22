"""Write node for generating draft content.

The Writer Agent generates draft chunks following the chapter briefs,
incorporating verified claims and maintaining style consistency.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ClaimStatus, DraftChunk
from prolific.services.embedding import get_embedding_service
from prolific.services.llm import get_llm_service
from prolific.rag.indexes import MultiIndexRAG
from prolific.rag.retrieval import WriterRetrievalService

logger = logging.getLogger(__name__)

WRITER_SYSTEM_PROMPT = """You are an expert writer creating content for a book/article.

Chapter {chapter_num}: {title}

Thesis: {thesis}

Key points to cover:
{key_points}

Style requirements:
- Tone: {tone}
- Formality: {formality}
- Use contractions: {contractions}
- Citation style: {citation_style}

Word count target: {word_target} words (min: {word_min}, max: {word_max})

IMPORTANT CONSTRAINTS:
1. You MUST incorporate the required claims with proper citations
2. Do NOT repeat content from previous chapters (see context below)
3. Maintain consistent terminology with the glossary
4. Write engaging, well-structured prose
5. Include smooth transitions between sections

{context}"""


async def write_node(state: ContentGenerationState) -> dict:
    """Generate draft content for chapters.

    This node (can run in parallel per chapter):
    1. Retrieves relevant context from RAG
    2. Incorporates required claims
    3. Generates draft content following the brief
    4. Creates DraftChunk artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with draft_chunks to merge into state
    """
    chapter_briefs = state.get("chapter_briefs", [])
    existing_chunks = state.get("draft_chunks", [])
    claims = {c.id: c for c in state.get("claims", [])}

    written_chapters = {chunk.chapter_id for chunk in existing_chunks}
    briefs_to_write = [
        b for b in chapter_briefs if b.chapter_id not in written_chapters
    ]

    if not briefs_to_write:
        logger.info("All chapters already written")
        return {
            "current_phase": "summarize",
            "writing_complete": True,
            "messages": [AIMessage(content="All chapters already written.")],
        }

    logger.info(f"=== WRITING PHASE ===")
    logger.info(f"Chapters to write: {len(briefs_to_write)}")
    logger.info(f"Expected LLM calls: {len(briefs_to_write)} (1 per chapter, using premium writing model)")

    llm_service = get_llm_service()
    embedding_service = get_embedding_service()

    try:
        rag = MultiIndexRAG()
        retrieval_service = WriterRetrievalService(rag)
    except Exception as e:
        logger.warning(f"Could not initialize RAG: {e}")
        retrieval_service = None

    global_memory = state.get("global_memory")
    style_guide = global_memory.style_guide if global_memory else None

    draft_chunks = []

    for brief_idx, brief in enumerate(briefs_to_write, 1):
        try:
            logger.info(f"[{brief_idx}/{len(briefs_to_write)}] Writing chapter {brief.chapter_number}: {brief.title}")
            logger.info(f"  - Target: {brief.word_count_target} words, {len(brief.required_claims)} required claims")

            context_parts = []

            if retrieval_service:
                try:
                    brief_text = f"{brief.title} {brief.thesis_statement} {' '.join(brief.key_points)}"
                    query_embedding = await embedding_service.embed_text(brief_text)

                    retrieval_results = await retrieval_service.retrieve_for_writer(
                        query_embedding=query_embedding,
                        chapter_id=str(brief.chapter_id),
                        required_claim_ids=[str(cid) for cid in brief.required_claims],
                    )

                    context_str = retrieval_service.build_writer_context(retrieval_results)
                    if context_str:
                        context_parts.append(context_str)

                except Exception as e:
                    logger.warning(f"RAG retrieval failed: {e}")

            required_claims_text = []
            for claim_id in brief.required_claims:
                claim = claims.get(claim_id)
                if claim and claim.status == ClaimStatus.VERIFIED:
                    required_claims_text.append(f"- {claim.statement}")

            if required_claims_text:
                context_parts.append(
                    "## Required Claims (MUST include with citations):\n"
                    + "\n".join(required_claims_text)
                )

            if global_memory and global_memory.rolling_summary:
                context_parts.append(
                    f"## Previous Content Summary:\n{global_memory.rolling_summary}"
                )

            context = "\n\n".join(context_parts) if context_parts else "No additional context."

            key_points_str = "\n".join(f"- {point}" for point in brief.key_points)

            system_message = SystemMessage(
                content=WRITER_SYSTEM_PROMPT.format(
                    chapter_num=brief.chapter_number,
                    title=brief.title,
                    thesis=brief.thesis_statement,
                    key_points=key_points_str,
                    tone=style_guide.tone if style_guide else "academic",
                    formality=style_guide.formality_level if style_guide else 0.7,
                    contractions="yes" if style_guide and style_guide.use_contractions else "no",
                    citation_style=style_guide.citation_style if style_guide else "inline",
                    word_target=brief.word_count_target,
                    word_min=brief.word_count_min,
                    word_max=brief.word_count_max,
                    context=context,
                )
            )

            user_message = HumanMessage(
                content=f"""Write chapter {brief.chapter_number}: "{brief.title}"

Remember to:
1. Start with an engaging opening
2. Cover all key points in logical order
3. Incorporate required claims with citations
4. End with a transition to the next topic
5. Stay within {brief.word_count_min}-{brief.word_count_max} words

Write the complete chapter now."""
            )

            response = await llm_service.invoke(
                messages=[system_message, user_message],
                tier="writing",
                temperature=0.7,
                max_tokens=4000,
            )

            content = response.content
            word_count = len(content.split())

            chunk = DraftChunk(
                id=uuid4(),
                chapter_id=brief.chapter_id,
                brief_id=brief.id,
                section_index=0,
                content=content,
                word_count=word_count,
                claims_referenced=brief.required_claims,
                style_compliance_score=0.8,
            )
            draft_chunks.append(chunk)

            logger.info(
                f"Completed chapter {brief.chapter_number}: {word_count} words"
            )

        except Exception as e:
            logger.error(f"Failed to write chapter {brief.chapter_number}: {e}")
            state.get("errors", []).append(
                f"Failed to write chapter {brief.chapter_number}: {e}"
            )

    total_words = sum(chunk.word_count for chunk in draft_chunks)
    logger.info(f"Writing complete: {len(draft_chunks)} chapters, {total_words} total words")

    return {
        "draft_chunks": draft_chunks,
        "current_phase": "summarize",
        "writing_complete": True,
        "messages": [
            AIMessage(
                content=f"Wrote {len(draft_chunks)} chapters ({total_words} words)."
            )
        ],
    }
