"""Write node for generating draft content.

The Writer Agent generates draft chunks following the chapter briefs,
incorporating verified claims and maintaining style consistency.

For long chapters (>3000 words), content is split into sections with
separate LLM calls to maintain quality and avoid context limits.
"""

import logging
import math
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ClaimStatus, DraftChunk
from prolific.services.embedding import get_embedding_service
from prolific.services.llm import get_llm_service
from prolific.rag.indexes import MultiIndexRAG
from prolific.rag.retrieval import WriterRetrievalService

logger = logging.getLogger(__name__)

SECTION_WORD_THRESHOLD = 3000
MAX_WORDS_PER_SECTION = 2000

WRITER_SYSTEM_PROMPT = """You are an expert writer creating content for a book/article.

Chapter {chapter_num}: {title}

Thesis: {thesis}

Key points to cover:
{key_points}

Style requirements:
- Tone: {tone}
- Formality: {formality}
- Use contractions: {contractions}

Word count target: {word_target} words (min: {word_min}, max: {word_max})

CITATION INSTRUCTIONS:
When incorporating facts from the required claims below, include the bracketed citation number [N] inline.
For example: "Studies show that certain bacteria play a key role in vaginal health [1]."
Multiple citations can be combined: "Recent research [2, 3] demonstrates..."
Place citations naturally within sentences after the relevant fact, not at paragraph ends.

IMPORTANT CONSTRAINTS:
1. You MUST incorporate the required claims WITH their [N] citation numbers shown in the claims list
2. Do NOT repeat content from previous chapters (see context below)
3. Maintain consistent terminology with the glossary
4. Write engaging, well-structured prose
5. Include smooth transitions between sections

{context}"""

SECTION_SYSTEM_PROMPT = """You are an expert writer creating a SECTION of a chapter.

Chapter {chapter_num}: {title}
Section {section_num} of {total_sections}: {section_title}

Chapter thesis: {thesis}

This section should cover:
{section_points}

Style requirements:
- Tone: {tone}
- Formality: {formality}
- Use contractions: {contractions}

Word count target for this section: {word_target} words

CITATION INSTRUCTIONS:
When incorporating facts from the required claims below, include the bracketed citation number [N] inline.

IMPORTANT CONSTRAINTS:
1. You MUST incorporate any relevant claims with their [N] citation numbers
2. Do NOT repeat content from previous sections or chapters (see context below)
3. Maintain consistent terminology with the glossary
4. Write engaging, well-structured prose
5. {transition_instruction}

{context}"""


async def write_section(
    llm_service,
    chapter_num: int,
    title: str,
    thesis: str,
    section_num: int,
    total_sections: int,
    section_points: list[str],
    section_word_target: int,
    style_guide,
    context: str,
    claims_text: str,
    previous_section_ending: str | None = None,
) -> tuple[str, int]:
    """Write a single section of a chapter.

    Args:
        llm_service: LLM service for generation
        chapter_num: Chapter number
        title: Chapter title
        thesis: Chapter thesis statement
        section_num: Current section number (1-indexed)
        total_sections: Total number of sections
        section_points: Key points to cover in this section
        section_word_target: Word count target for this section
        style_guide: Style guide for writing
        context: RAG context and claims
        claims_text: Required claims text with citations
        previous_section_ending: Last paragraph of previous section for continuity

    Returns:
        Tuple of (section_content, word_count)
    """
    section_title = f"Part {section_num}"
    if section_num == 1:
        transition_instruction = "Start with an engaging opening for the chapter"
    elif section_num == total_sections:
        transition_instruction = "End with a strong conclusion and transition to the next chapter"
    else:
        transition_instruction = "Begin with a smooth transition from the previous section"

    section_context_parts = []
    if claims_text:
        section_context_parts.append(claims_text)
    if context:
        section_context_parts.append(context)
    if previous_section_ending:
        section_context_parts.append(
            f"## Previous Section Ending (continue naturally from here):\n...{previous_section_ending}"
        )

    full_context = "\n\n".join(section_context_parts) if section_context_parts else "No additional context."

    system_message = SystemMessage(
        content=SECTION_SYSTEM_PROMPT.format(
            chapter_num=chapter_num,
            title=title,
            section_num=section_num,
            total_sections=total_sections,
            section_title=section_title,
            thesis=thesis,
            section_points="\n".join(f"- {p}" for p in section_points),
            tone=style_guide.tone if style_guide else "academic",
            formality=style_guide.formality_level if style_guide else 0.7,
            contractions="yes" if style_guide and style_guide.use_contractions else "no",
            word_target=section_word_target,
            transition_instruction=transition_instruction,
            context=full_context,
        )
    )

    user_message = HumanMessage(
        content=f"""Write section {section_num} of {total_sections} for chapter {chapter_num}: "{title}"

Cover these points:
{chr(10).join(f'- {p}' for p in section_points)}

Target: approximately {section_word_target} words.

Write the section now."""
    )

    response = await llm_service.invoke(
        messages=[system_message, user_message],
        tier="writing",
        temperature=0.7,
        max_tokens=3000,
    )

    content = response.content
    word_count = len(content.split())
    return content, word_count


def split_points_into_sections(
    key_points: list[str],
    word_count_target: int,
) -> list[tuple[list[str], int]]:
    """Split key points into sections based on word count target.

    Args:
        key_points: List of key points to cover
        word_count_target: Total word count target for the chapter

    Returns:
        List of (section_points, section_word_target) tuples
    """
    num_sections = math.ceil(word_count_target / MAX_WORDS_PER_SECTION)
    num_sections = max(2, min(num_sections, len(key_points)))

    points_per_section = math.ceil(len(key_points) / num_sections)
    words_per_section = word_count_target // num_sections

    sections = []
    for i in range(num_sections):
        start_idx = i * points_per_section
        end_idx = min((i + 1) * points_per_section, len(key_points))
        section_points = key_points[start_idx:end_idx]

        if i == num_sections - 1:
            section_points = key_points[start_idx:]

        if section_points:
            sections.append((section_points, words_per_section))

    return sections


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
    approved_sources = {s.id: s for s in state.get("approved_sources", [])}

    # Build global reference list from all approved sources
    source_to_ref_num = {}
    ref_num_to_source = {}
    for idx, source in enumerate(state.get("approved_sources", []), 1):
        source_to_ref_num[source.id] = idx
        ref_num_to_source[idx] = source

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

    estimated_calls = 0
    for b in briefs_to_write:
        if b.word_count_target > SECTION_WORD_THRESHOLD and len(b.key_points) >= 2:
            num_sections = math.ceil(b.word_count_target / MAX_WORDS_PER_SECTION)
            estimated_calls += max(2, min(num_sections, len(b.key_points)))
        else:
            estimated_calls += 1
    logger.info(f"Estimated LLM calls: {estimated_calls} (long chapters split into sections)")

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
    thread_id = state.get("thread_id")

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
                        thread_id=thread_id,
                    )

                    context_str = retrieval_service.build_writer_context(retrieval_results)
                    if context_str:
                        context_parts.append(context_str)

                except Exception as e:
                    logger.warning(f"RAG retrieval failed: {e}")

            required_claims_text = []
            chapter_ref_nums = set()  # Track which references are used in this chapter
            for claim_id in brief.required_claims:
                claim = claims.get(claim_id)
                if claim and claim.status == ClaimStatus.VERIFIED:
                    # Get reference numbers for this claim's sources
                    ref_nums = []
                    for source_id in claim.source_ids:
                        if source_id in source_to_ref_num:
                            ref_num = source_to_ref_num[source_id]
                            ref_nums.append(ref_num)
                            chapter_ref_nums.add(ref_num)

                    if ref_nums:
                        citation = "[" + ", ".join(str(n) for n in sorted(ref_nums)) + "]"
                        required_claims_text.append(f"- {claim.statement} {citation}")
                    else:
                        required_claims_text.append(f"- {claim.statement}")

            if required_claims_text:
                context_parts.append(
                    "## Required Claims (include the [N] citation when using each fact):\n"
                    + "\n".join(required_claims_text)
                )

            if global_memory and global_memory.rolling_summary:
                context_parts.append(
                    f"## Previous Content Summary:\n{global_memory.rolling_summary}"
                )

            context = "\n\n".join(context_parts) if context_parts else "No additional context."

            claims_context = ""
            if required_claims_text:
                claims_context = (
                    "## Required Claims (include the [N] citation when using each fact):\n"
                    + "\n".join(required_claims_text)
                )

            if brief.word_count_target > SECTION_WORD_THRESHOLD and len(brief.key_points) >= 2:
                sections = split_points_into_sections(
                    brief.key_points, brief.word_count_target
                )
                logger.info(
                    f"  - Splitting into {len(sections)} sections for long chapter"
                )

                section_contents = []
                previous_ending = None
                total_section_words = 0

                for section_idx, (section_points, section_word_target) in enumerate(sections, 1):
                    logger.info(
                        f"  - Writing section {section_idx}/{len(sections)}: "
                        f"{len(section_points)} points, ~{section_word_target} words"
                    )

                    section_content, section_words = await write_section(
                        llm_service=llm_service,
                        chapter_num=brief.chapter_number,
                        title=brief.title,
                        thesis=brief.thesis_statement,
                        section_num=section_idx,
                        total_sections=len(sections),
                        section_points=section_points,
                        section_word_target=section_word_target,
                        style_guide=style_guide,
                        context=context,
                        claims_text=claims_context,
                        previous_section_ending=previous_ending,
                    )

                    section_contents.append(section_content)
                    total_section_words += section_words

                    paragraphs = section_content.strip().split("\n\n")
                    if paragraphs:
                        previous_ending = paragraphs[-1][-500:]

                content = "\n\n".join(section_contents)
                word_count = total_section_words
                logger.info(
                    f"  - Combined {len(sections)} sections: {word_count} words"
                )

            else:
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
