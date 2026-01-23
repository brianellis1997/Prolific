"""Summarize node for updating book memory.

The Summarizer Agent updates the rolling summary, glossary,
and book memory after new content is written.

Implements hierarchical summarization:
- Per-chapter summaries (stored individually)
- Part summaries (every N chapters, compressed into higher-level summary)
- Rolling summary built from part summaries + recent chapter summaries
"""

import logging
from datetime import datetime

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.memory import GlossaryEntry
from prolific.services.embedding import get_embedding_service
from prolific.services.llm import get_llm_service
from prolific.rag.indexes import MultiIndexRAG
from prolific.tools.writing_tools import generate_chapter_summary

logger = logging.getLogger(__name__)

PART_SUMMARY_PROMPT = """You are creating a condensed summary of multiple chapters for a long document.

The following are summaries of chapters {start_chapter} through {end_chapter}:

{chapter_summaries}

Create a single, cohesive paragraph that captures:
1. The main themes and progression across these chapters
2. Key facts and concepts introduced
3. How these chapters connect to the overall narrative

Keep the summary to 150-200 words, focusing on the most important information that would help a writer maintain consistency in later chapters."""


async def create_part_summary(
    llm_service,
    chapter_summaries: list[str],
    start_chapter: int,
    end_chapter: int,
) -> str:
    """Create a condensed summary of multiple chapters.

    Args:
        llm_service: LLM service for generation
        chapter_summaries: List of individual chapter summaries
        start_chapter: First chapter number in the part
        end_chapter: Last chapter number in the part

    Returns:
        Condensed part summary
    """
    summaries_text = "\n\n".join(
        f"**Chapter {start_chapter + i}:** {summary}"
        for i, summary in enumerate(chapter_summaries)
    )

    system_message = SystemMessage(
        content=PART_SUMMARY_PROMPT.format(
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            chapter_summaries=summaries_text,
        )
    )

    user_message = HumanMessage(
        content="Create the condensed part summary now."
    )

    response = await llm_service.invoke(
        messages=[system_message, user_message],
        tier="research",
        temperature=0.3,
        max_tokens=500,
    )

    return response.content


def build_hierarchical_rolling_summary(
    part_summaries: list[str],
    recent_chapter_summaries: list[str],
    max_length: int = 5000,
) -> str:
    """Build rolling summary from part summaries + recent chapter summaries.

    This ensures early chapters aren't lost while keeping context manageable.

    Args:
        part_summaries: List of compressed part summaries
        recent_chapter_summaries: Recent chapter summaries not yet in a part
        max_length: Maximum character length for the rolling summary

    Returns:
        Combined rolling summary
    """
    sections = []

    if part_summaries:
        sections.append("## Earlier Parts Summary")
        for i, part_summary in enumerate(part_summaries, 1):
            sections.append(f"**Part {i}:** {part_summary}")
        sections.append("")

    if recent_chapter_summaries:
        sections.append("## Recent Chapters")
        for summary in recent_chapter_summaries:
            sections.append(f"- {summary}")

    combined = "\n".join(sections)

    if len(combined) > max_length:
        if part_summaries and len(part_summaries) > 2:
            truncated_parts = part_summaries[-2:]
            return build_hierarchical_rolling_summary(
                truncated_parts, recent_chapter_summaries, max_length
            )
        combined = combined[-max_length:]

    return combined


async def summarize_node(state: ContentGenerationState) -> dict:
    """Update book memory with summaries of new content.

    This node:
    1. Generates summaries for new draft chunks
    2. Updates the rolling summary
    3. Extracts and adds new glossary terms
    4. Indexes content for RAG retrieval

    Args:
        state: Current workflow state

    Returns:
        Dict with updated global_memory to merge into state
    """
    logger.info("Summarize node starting")

    draft_chunks = state.get("draft_chunks", [])
    global_memory = state.get("global_memory")
    chapter_briefs = {b.chapter_id: b for b in state.get("chapter_briefs", [])}

    if not draft_chunks:
        logger.info("No draft chunks to summarize")
        return {
            "current_phase": "integrate",
            "messages": [AIMessage(content="No new content to summarize.")],
        }

    completed_chapter_ids = set(global_memory.completed_chapters) if global_memory else set()
    new_chunks = [
        chunk for chunk in draft_chunks
        if chunk.chapter_id not in completed_chapter_ids
    ]

    if not new_chunks:
        logger.info("All chunks already summarized")
        return {
            "current_phase": "integrate",
            "messages": [AIMessage(content="All content already summarized.")],
        }

    try:
        rag = MultiIndexRAG()
        embedding_service = get_embedding_service()
        use_rag = True
    except Exception as e:
        logger.warning(f"Could not initialize RAG/embeddings: {e}")
        use_rag = False

    llm_service = get_llm_service()
    new_chapter_summaries = []
    all_new_terms = []
    total_words = 0
    thread_id = state.get("thread_id")

    for chunk in new_chunks:
        try:
            brief = chapter_briefs.get(chunk.chapter_id)
            chapter_title = brief.title if brief else f"Chapter {chunk.section_index}"

            summary_result = await generate_chapter_summary.ainvoke({
                "chapter_content": chunk.content,
                "chapter_title": chapter_title,
                "max_length": 200,
            })

            chapter_summary = f"**{chapter_title}**: {summary_result.get('summary', '')}"
            new_chapter_summaries.append(chapter_summary)
            all_new_terms.extend(summary_result.get("new_terms", []))
            total_words += chunk.word_count

            if use_rag:
                summary_text = f"{chapter_title}: {summary_result.get('summary', '')}"
                summary_embedding = await embedding_service.embed_text(summary_text)

                rag.add_to_book_memory(
                    doc_id=f"summary_{chunk.chapter_id}",
                    text=summary_text,
                    embedding=summary_embedding,
                    metadata={
                        "type": "chapter_summary",
                        "chapter_id": str(chunk.chapter_id),
                        "chapter_title": chapter_title,
                    },
                    thread_id=thread_id,
                )

                chunk_embedding = await embedding_service.embed_text(chunk.content[:2000])

                rag.add_to_draft_chunks(
                    chunk_id=str(chunk.id),
                    text=chunk.content[:3000],
                    embedding=chunk_embedding,
                    chapter_id=str(chunk.chapter_id),
                    chapter_number=brief.chapter_number if brief else 0,
                    thread_id=thread_id,
                )

            if global_memory:
                global_memory.completed_chapters.append(chunk.chapter_id)

                for topic in summary_result.get("topics_covered", []):
                    global_memory.topics_covered.add(topic)
                    global_memory.topics_remaining.discard(topic)

        except Exception as e:
            logger.error(f"Failed to summarize chunk {chunk.id}: {e}")

    if global_memory:
        global_memory.chapter_summaries.extend(new_chapter_summaries)

        chapters_per_part = global_memory.chapters_per_part
        total_chapters = len(global_memory.chapter_summaries)
        existing_parts = len(global_memory.part_summaries)
        chapters_in_parts = existing_parts * chapters_per_part

        if total_chapters - chapters_in_parts >= chapters_per_part:
            start_idx = chapters_in_parts
            end_idx = start_idx + chapters_per_part
            chapters_to_compress = global_memory.chapter_summaries[start_idx:end_idx]

            try:
                part_summary = await create_part_summary(
                    llm_service=llm_service,
                    chapter_summaries=chapters_to_compress,
                    start_chapter=start_idx + 1,
                    end_chapter=end_idx,
                )
                global_memory.part_summaries.append(part_summary)
                logger.info(
                    f"Created part summary for chapters {start_idx + 1}-{end_idx}"
                )
            except Exception as e:
                logger.warning(f"Failed to create part summary: {e}")

        recent_start = len(global_memory.part_summaries) * chapters_per_part
        recent_chapter_summaries = global_memory.chapter_summaries[recent_start:]

        global_memory.rolling_summary = build_hierarchical_rolling_summary(
            part_summaries=global_memory.part_summaries,
            recent_chapter_summaries=recent_chapter_summaries,
            max_length=5000,
        )

        for term in all_new_terms:
            if term and term not in global_memory.glossary:
                global_memory.glossary[term] = GlossaryEntry(
                    term=term,
                    definition="",
                    first_introduced_chapter=len(global_memory.completed_chapters),
                )

        global_memory.current_word_count += total_words
        global_memory.updated_at = datetime.utcnow()

    logger.info(
        f"Summarized {len(new_chunks)} chapters. "
        f"Total words: {global_memory.current_word_count if global_memory else total_words}"
    )

    return {
        "global_memory": global_memory,
        "current_phase": "integrate",
        "messages": [
            AIMessage(
                content=f"Summarized {len(new_chunks)} chapters. "
                f"Rolling summary updated. {len(all_new_terms)} new terms found."
            )
        ],
    }
