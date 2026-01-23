"""Content generation API endpoints."""

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import json

from prolific.agent.graph import run_content_generation, stream_content_generation
from prolific.services.checkpointer import get_checkpointer_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/generation", tags=["generation"])


class GenerationRequest(BaseModel):
    """Request to generate content."""

    topic: str = Field(..., description="Main topic for the content")
    subtopics: list[str] = Field(default_factory=list, description="Subtopics to cover")
    focus_areas: list[str] = Field(default_factory=list, description="Areas to focus on")
    target_word_count: int = Field(default=5000, ge=500, le=200000, description="Target word count")
    depth: str = Field(default="standard", description="Depth level: overview, standard, deep, exhaustive")
    style_tone: str = Field(default="academic", description="Writing tone")
    citation_style: str = Field(default="inline", description="Citation style")
    max_iterations: int = Field(default=3, ge=1, le=10, description="Max research iterations")
    thread_id: str | None = Field(default=None, description="Thread ID to resume from (optional)")


class GenerationResponse(BaseModel):
    """Response from content generation."""

    status: str
    thread_id: str = ""  # For resume capability
    topic: str
    word_count: int
    chapter_count: int
    source_count: int
    claim_count: int
    content: list[dict]  # List of chapter contents
    references: str = ""  # Bibliography section
    warnings: list[str]


class GenerationProgress(BaseModel):
    """Progress update during generation."""

    node: str
    phase: str
    iteration: int
    source_count: int
    claim_count: int
    chapter_count: int
    word_count: int
    messages: list[str]


@router.post("/create", response_model=GenerationResponse)
async def create_content(request: GenerationRequest):
    """Generate content for a topic.

    This endpoint runs the full content generation pipeline
    and returns the complete result. Pass thread_id to resume
    a previous generation.
    """
    try:
        logger.info(f"Starting content generation for: {request.topic}")

        style_preferences = {
            "tone": request.style_tone,
            "citation_style": request.citation_style,
        }

        final_state, thread_id = await run_content_generation(
            topic=request.topic,
            subtopics=request.subtopics,
            focus_areas=request.focus_areas,
            target_word_count=request.target_word_count,
            depth=request.depth,
            style_preferences=style_preferences,
            max_iterations=request.max_iterations,
            thread_id=request.thread_id,
        )

        draft_chunks = final_state.get("draft_chunks", [])
        chapter_briefs = {b.chapter_id: b for b in final_state.get("chapter_briefs", [])}

        content = []
        for chunk in sorted(draft_chunks, key=lambda c: chapter_briefs.get(c.chapter_id, type("", (), {"chapter_number": 0})).chapter_number):
            brief = chapter_briefs.get(chunk.chapter_id)
            content.append({
                "chapter_number": brief.chapter_number if brief else 0,
                "title": brief.title if brief else "Untitled",
                "content": chunk.content,
                "word_count": chunk.word_count,
            })

        global_memory = final_state.get("global_memory")
        references = global_memory.references_section if global_memory else ""

        return GenerationResponse(
            status="complete",
            thread_id=thread_id,
            topic=request.topic,
            word_count=sum(c.word_count for c in draft_chunks),
            chapter_count=len(draft_chunks),
            source_count=len(final_state.get("approved_sources", [])),
            claim_count=len(final_state.get("claims", [])),
            content=content,
            references=references,
            warnings=final_state.get("warnings", []),
        )

    except Exception as e:
        logger.error(f"Content generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def stream_content(request: GenerationRequest):
    """Stream content generation with progress updates.

    This endpoint streams progress updates as the content
    is being generated, useful for long-running generations.
    Pass thread_id to resume a previous generation.
    """
    async def generate() -> AsyncGenerator[str, None]:
        final_state = None
        thread_id = None
        try:
            style_preferences = {
                "tone": request.style_tone,
                "citation_style": request.citation_style,
            }

            async for progress in stream_content_generation(
                topic=request.topic,
                subtopics=request.subtopics,
                focus_areas=request.focus_areas,
                target_word_count=request.target_word_count,
                depth=request.depth,
                style_preferences=style_preferences,
                max_iterations=request.max_iterations,
                thread_id=request.thread_id,
            ):
                if "_final_state" in progress:
                    final_state = progress["_final_state"]
                    thread_id = progress.get("thread_id", thread_id)
                    logger.info(f"Captured final_state with {len(final_state.get('draft_chunks', []))} chunks")
                else:
                    thread_id = progress.get("thread_id", thread_id)
                    yield f"data: {json.dumps(progress)}\n\n"

            if final_state:
                logger.info(f"Final state received. Building result...")
                draft_chunks = final_state.get("draft_chunks", [])
                chapter_briefs = {b.chapter_id: b for b in final_state.get("chapter_briefs", [])}

                content = []
                for chunk in sorted(draft_chunks, key=lambda c: chapter_briefs.get(c.chapter_id, type("", (), {"chapter_number": 0})).chapter_number):
                    brief = chapter_briefs.get(chunk.chapter_id)
                    content.append({
                        "chapter_number": brief.chapter_number if brief else 0,
                        "title": brief.title if brief else "Untitled",
                        "content": chunk.content,
                        "word_count": chunk.word_count,
                    })

                global_memory = final_state.get("global_memory")
                references = global_memory.references_section if global_memory else ""

                result = {
                    "status": "complete",
                    "thread_id": thread_id,
                    "topic": request.topic,
                    "word_count": sum(c.word_count for c in draft_chunks),
                    "chapter_count": len(draft_chunks),
                    "source_count": len(final_state.get("approved_sources", [])),
                    "claim_count": len(final_state.get("claims", [])),
                    "content": content,
                    "references": references,
                    "warnings": final_state.get("warnings", []),
                }
                logger.info(f"Sending complete result: {len(content)} chapters, {result['word_count']} words")
                yield f"data: {json.dumps(result)}\n\n"
            else:
                logger.warning("No final_state received - sending empty complete")
                yield f"data: {json.dumps({'status': 'complete', 'thread_id': thread_id})}\n\n"

        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e), 'thread_id': thread_id})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/threads")
async def list_threads():
    """List all generation threads with their status.

    Returns a list of threads that can be resumed.
    """
    try:
        checkpointer_service = get_checkpointer_service()
        threads = await checkpointer_service.list_threads()
        return {"threads": threads}
    except Exception as e:
        logger.error(f"Failed to list threads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    """Get the current state of a specific generation thread.

    Args:
        thread_id: The thread ID to retrieve
    """
    try:
        checkpointer_service = get_checkpointer_service()
        state = await checkpointer_service.get_thread_state(thread_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Thread not found")

        draft_chunks = state.get("draft_chunks", [])
        chapter_briefs = {b.chapter_id: b for b in state.get("chapter_briefs", [])}

        content = []
        for chunk in sorted(draft_chunks, key=lambda c: chapter_briefs.get(c.chapter_id, type("", (), {"chapter_number": 0})).chapter_number):
            brief = chapter_briefs.get(chunk.chapter_id)
            content.append({
                "chapter_number": brief.chapter_number if brief else 0,
                "title": brief.title if brief else "Untitled",
                "content": chunk.content,
                "word_count": chunk.word_count,
            })

        global_memory = state.get("global_memory")
        references = global_memory.references_section if global_memory else ""

        return {
            "thread_id": thread_id,
            "topic": state.get("topic", "Unknown"),
            "phase": state.get("current_phase", "unknown"),
            "iteration": state.get("iteration_count", 0),
            "word_count": sum(c.word_count for c in draft_chunks),
            "chapter_count": len(draft_chunks),
            "source_count": len(state.get("approved_sources", [])),
            "claim_count": len(state.get("claims", [])),
            "content": content,
            "references": references,
            "warnings": state.get("warnings", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get thread {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete a generation thread and its checkpoints.

    Args:
        thread_id: The thread ID to delete
    """
    try:
        checkpointer_service = get_checkpointer_service()
        deleted = await checkpointer_service.delete_thread(thread_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Thread not found")
        return {"status": "deleted", "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete thread {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Check if the generation service is healthy."""
    return {"status": "healthy", "service": "content-generation"}
