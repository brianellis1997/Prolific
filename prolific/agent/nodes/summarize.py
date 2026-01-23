"""Summarize node for updating book memory.

The Summarizer Agent updates the rolling summary, glossary,
and book memory after new content is written.
"""

import logging
from datetime import datetime

from langchain_core.messages import AIMessage

from prolific.agent.state import ContentGenerationState
from prolific.schemas.memory import GlossaryEntry
from prolific.services.embedding import get_embedding_service
from prolific.rag.indexes import MultiIndexRAG
from prolific.tools.writing_tools import generate_chapter_summary

logger = logging.getLogger(__name__)


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

    chapter_summaries = []
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

            chapter_summaries.append(
                f"**{chapter_title}**: {summary_result.get('summary', '')}"
            )
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
        global_memory.rolling_summary = (
            f"{global_memory.rolling_summary}\n\n" if global_memory.rolling_summary else ""
        ) + "\n\n".join(chapter_summaries)

        if len(global_memory.rolling_summary) > 5000:
            global_memory.rolling_summary = global_memory.rolling_summary[-5000:]

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
