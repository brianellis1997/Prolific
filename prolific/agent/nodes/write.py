"""Write node for generating draft content.

The Writer Agent generates draft chunks section-by-section,
incorporating verified claims with inline hyperlinks and maintaining
style consistency across the document.
"""

import logging
import re
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ClaimStatus, DraftChunk
from prolific.services.embedding import get_embedding_service
from prolific.services.llm import get_llm_service
from prolific.rag.indexes import MultiIndexRAG
from prolific.rag.retrieval import WriterRetrievalService

logger = logging.getLogger(__name__)

SECTION_WRITER_PROMPT = """You are an expert writer creating a section of a larger document.

Chapter {chapter_num}: {chapter_title}
Section {section_num}: {section_title}

Chapter thesis: {thesis}

This section should cover:
{key_points}

Style requirements:
- Tone: {tone}
- Write engaging, well-structured prose
- Use smooth transitions between paragraphs

Word count target: {word_target} words (min: {word_min}, max: {word_max})

CITATION AND HYPERLINK INSTRUCTIONS:
You have access to verified claims with their source URLs. When incorporating facts:

1. Include bracketed citation numbers [N] after relevant facts
2. For specific entities, products, studies, or organizations mentioned in claims,
   use markdown hyperlinks to the source: [Entity Name](URL)
3. Be selective with hyperlinks - only link key terms that readers might want to explore
4. Don't over-link common terms, only notable proper nouns and specific references

Example:
"The [Kargu-2 drone](https://example.com/kargu) represents a new class of autonomous weapons [1]."

{claims_section}

IMPORTANT CONSTRAINTS:
1. Incorporate required claims with citations and strategic hyperlinks
2. Do NOT repeat content from previous sections (see context below)
3. Maintain consistent terminology
4. {transition_instruction}

{context}"""


def extract_hyperlinks_used(content: str) -> list[str]:
    """Extract all URLs used in markdown hyperlinks from content.

    Args:
        content: Written content with markdown links

    Returns:
        List of URLs found in hyperlinks
    """
    pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    matches = re.findall(pattern, content)
    return [url for _, url in matches]


def strip_leading_heading(content: str) -> str:
    """Remove any leading heading from content.

    LLMs sometimes include a heading even when asked not to.
    This strips any leading # heading lines.

    Args:
        content: Written content that may start with a heading

    Returns:
        Content with leading heading removed
    """
    lines = content.strip().split('\n')
    while lines and lines[0].strip().startswith('#'):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return '\n'.join(lines).strip()


def build_claims_with_urls(
    claims: dict,
    claim_ids: list,
    claim_urls: dict[str, str],
    source_to_ref_num: dict,
) -> str:
    """Build claims text with URLs for hyperlink generation.

    Args:
        claims: Dict of claim_id -> Claim
        claim_ids: List of claim IDs to include
        claim_urls: Dict mapping claim_id (str) -> source URL
        source_to_ref_num: Dict mapping source_id -> reference number

    Returns:
        Formatted claims text with citation numbers and URLs
    """
    claims_lines = []

    for claim_id in claim_ids:
        claim = claims.get(claim_id)
        if not claim or claim.status != ClaimStatus.VERIFIED:
            continue

        ref_nums = []
        for source_id in claim.source_ids:
            if source_id in source_to_ref_num:
                ref_nums.append(source_to_ref_num[source_id])

        citation = f"[{', '.join(str(n) for n in sorted(ref_nums))}]" if ref_nums else ""
        url = claim_urls.get(str(claim_id), "")

        if url:
            claims_lines.append(
                f"- {claim.statement} {citation}\n"
                f"  Source URL: {url}"
            )
        else:
            claims_lines.append(f"- {claim.statement} {citation}")

    if claims_lines:
        return (
            "## Required Claims (use [N] citations, add hyperlinks to key terms):\n"
            + "\n".join(claims_lines)
        )
    return ""


async def write_section(
    llm_service,
    chapter_num: int,
    chapter_title: str,
    thesis: str,
    section_num: int,
    section_title: str,
    key_points: list[str],
    word_target: int,
    style_guide,
    claims_text: str,
    context: str,
    is_first_section: bool,
    is_last_section: bool,
    previous_ending: str | None = None,
) -> tuple[str, int, list[str]]:
    """Write a single section of a chapter.

    Returns:
        Tuple of (content, word_count, hyperlinks_used)
    """
    if is_first_section:
        transition_instruction = "Start with an engaging opening for the chapter"
    elif is_last_section:
        transition_instruction = "End with a strong conclusion and smooth transition"
    else:
        transition_instruction = "Begin with a smooth transition from the previous section"

    context_parts = []
    if claims_text:
        context_parts.append(claims_text)
    if context:
        context_parts.append(context)
    if previous_ending:
        context_parts.append(
            f"## Previous Section Ending (continue naturally):\n...{previous_ending}"
        )

    full_context = "\n\n".join(context_parts) if context_parts else "No additional context."

    system_message = SystemMessage(
        content=SECTION_WRITER_PROMPT.format(
            chapter_num=chapter_num,
            chapter_title=chapter_title,
            section_num=section_num,
            section_title=section_title,
            thesis=thesis,
            key_points="\n".join(f"- {p}" for p in key_points),
            tone=style_guide.tone if style_guide else "academic",
            word_target=word_target,
            word_min=int(word_target * 0.8),
            word_max=int(word_target * 1.2),
            claims_section=claims_text,
            transition_instruction=transition_instruction,
            context=full_context,
        )
    )

    user_message = HumanMessage(
        content=f"""Write section {section_num} "{section_title}" for chapter {chapter_num}.

Cover these points:
{chr(10).join(f'- {p}' for p in key_points)}

Target: {word_target} words.
Remember to use markdown hyperlinks for key entities that have source URLs.

IMPORTANT: Do NOT include a section heading or title at the start - just begin writing the content directly. The heading will be added automatically.

Write the section now."""
    )

    response = await llm_service.invoke(
        messages=[system_message, user_message],
        tier="writing",
        temperature=0.7,
        max_tokens=3000,
    )

    content = response.content
    content = strip_leading_heading(content)
    word_count = len(content.split())
    hyperlinks = extract_hyperlinks_used(content)

    return content, word_count, hyperlinks


async def write_node(state: ContentGenerationState) -> dict:
    """Generate draft content section-by-section.

    This node:
    1. Iterates through chapters and their sections
    2. Retrieves relevant context from RAG
    3. Writes each section with claims and hyperlinks
    4. Creates DraftChunk artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with draft_chunks to merge into state
    """
    chapter_briefs = state.get("chapter_briefs", [])
    existing_chunks = state.get("draft_chunks", [])
    claims = {c.id: c for c in state.get("claims", [])}
    approved_sources = state.get("approved_sources", [])

    source_to_ref_num = {}
    for idx, source in enumerate(approved_sources, 1):
        source_to_ref_num[source.id] = idx

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

    logger.info("=== WRITING PHASE ===")
    logger.info(f"Chapters to write: {len(briefs_to_write)}")

    total_sections = sum(
        len(b.section_briefs) if b.section_briefs else 1
        for b in briefs_to_write
    )
    logger.info(f"Total sections to write: {total_sections}")

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
    section_count = 0

    for brief_idx, chapter_brief in enumerate(briefs_to_write, 1):
        logger.info(
            f"[{brief_idx}/{len(briefs_to_write)}] Writing chapter {chapter_brief.chapter_number}: "
            f"{chapter_brief.title}"
        )

        chapter_context = ""
        if retrieval_service:
            try:
                brief_text = (
                    f"{chapter_brief.title} {chapter_brief.thesis_statement} "
                    f"{' '.join(chapter_brief.key_points)}"
                )
                query_embedding = await embedding_service.embed_text(brief_text)

                retrieval_results = await retrieval_service.retrieve_for_writer(
                    query_embedding=query_embedding,
                    chapter_id=str(chapter_brief.chapter_id),
                    required_claim_ids=[str(cid) for cid in chapter_brief.required_claims],
                    thread_id=thread_id,
                    section_word_target=chapter_brief.word_count_target,
                )
                chapter_context = retrieval_service.build_writer_context(retrieval_results)
            except Exception as e:
                logger.warning(f"RAG retrieval failed: {e}")

        if chapter_brief.section_briefs:
            section_contents = []
            previous_ending = None
            chapter_hyperlinks = []

            for section_idx, section_brief in enumerate(chapter_brief.section_briefs):
                section_count += 1
                is_first = section_idx == 0
                is_last = section_idx == len(chapter_brief.section_briefs) - 1

                logger.info(
                    f"  Section {section_brief.section_number}: {section_brief.title} "
                    f"(~{section_brief.word_count_target} words)"
                )

                claims_text = build_claims_with_urls(
                    claims=claims,
                    claim_ids=section_brief.required_claims,
                    claim_urls=section_brief.claim_urls,
                    source_to_ref_num=source_to_ref_num,
                )

                content, word_count, hyperlinks = await write_section(
                    llm_service=llm_service,
                    chapter_num=chapter_brief.chapter_number,
                    chapter_title=chapter_brief.title,
                    thesis=chapter_brief.thesis_statement,
                    section_num=section_brief.section_number,
                    section_title=section_brief.title,
                    key_points=section_brief.key_points,
                    word_target=section_brief.word_count_target,
                    style_guide=style_guide,
                    claims_text=claims_text,
                    context=chapter_context,
                    is_first_section=is_first,
                    is_last_section=is_last,
                    previous_ending=previous_ending,
                )

                section_contents.append(f"## {section_brief.title}\n\n{content}")
                chapter_hyperlinks.extend(hyperlinks)

                paragraphs = content.strip().split("\n\n")
                if paragraphs:
                    previous_ending = paragraphs[-1][-500:]

                logger.info(f"    Written: {word_count} words, {len(hyperlinks)} hyperlinks")

            full_content = "\n\n".join(section_contents)
            total_words = len(full_content.split())

            chunk = DraftChunk(
                id=uuid4(),
                part_id=chapter_brief.part_id,
                chapter_id=chapter_brief.chapter_id,
                brief_id=chapter_brief.id,
                section_index=0,
                content=full_content,
                word_count=total_words,
                claims_referenced=chapter_brief.required_claims,
                hyperlinks_used=chapter_hyperlinks,
                style_compliance_score=0.8,
            )
            draft_chunks.append(chunk)

            logger.info(
                f"Completed chapter {chapter_brief.chapter_number}: "
                f"{total_words} words, {len(chapter_hyperlinks)} hyperlinks"
            )

        else:
            logger.info(f"  No section briefs - writing chapter as single unit")

            claims_text = build_claims_with_urls(
                claims=claims,
                claim_ids=chapter_brief.required_claims,
                claim_urls={},
                source_to_ref_num=source_to_ref_num,
            )

            content, word_count, hyperlinks = await write_section(
                llm_service=llm_service,
                chapter_num=chapter_brief.chapter_number,
                chapter_title=chapter_brief.title,
                thesis=chapter_brief.thesis_statement,
                section_num=1,
                section_title=chapter_brief.title,
                key_points=chapter_brief.key_points,
                word_target=chapter_brief.word_count_target,
                style_guide=style_guide,
                claims_text=claims_text,
                context=chapter_context,
                is_first_section=True,
                is_last_section=True,
            )

            chunk = DraftChunk(
                id=uuid4(),
                part_id=chapter_brief.part_id,
                chapter_id=chapter_brief.chapter_id,
                brief_id=chapter_brief.id,
                section_index=0,
                content=content,
                word_count=word_count,
                claims_referenced=chapter_brief.required_claims,
                hyperlinks_used=hyperlinks,
                style_compliance_score=0.8,
            )
            draft_chunks.append(chunk)

            logger.info(f"Completed chapter {chapter_brief.chapter_number}: {word_count} words")

    total_words = sum(chunk.word_count for chunk in draft_chunks)
    total_hyperlinks = sum(len(chunk.hyperlinks_used) for chunk in draft_chunks)

    logger.info(
        f"Writing complete: {len(draft_chunks)} chapters, "
        f"{total_words} words, {total_hyperlinks} hyperlinks"
    )

    return {
        "draft_chunks": draft_chunks,
        "current_phase": "summarize",
        "writing_complete": True,
        "messages": [
            AIMessage(
                content=f"Wrote {len(draft_chunks)} chapters ({total_words} words, "
                f"{total_hyperlinks} inline hyperlinks)."
            )
        ],
    }
