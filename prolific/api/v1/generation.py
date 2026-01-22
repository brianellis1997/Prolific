"""Content generation API endpoints."""

import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import json

from prolific.agent.graph import run_content_generation, stream_content_generation

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


class GenerationResponse(BaseModel):
    """Response from content generation."""

    status: str
    topic: str
    word_count: int
    chapter_count: int
    source_count: int
    claim_count: int
    content: list[dict]  # List of chapter contents
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
    and returns the complete result.
    """
    try:
        logger.info(f"Starting content generation for: {request.topic}")

        style_preferences = {
            "tone": request.style_tone,
            "citation_style": request.citation_style,
        }

        final_state = await run_content_generation(
            topic=request.topic,
            subtopics=request.subtopics,
            focus_areas=request.focus_areas,
            target_word_count=request.target_word_count,
            depth=request.depth,
            style_preferences=style_preferences,
            max_iterations=request.max_iterations,
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

        return GenerationResponse(
            status="complete",
            topic=request.topic,
            word_count=sum(c.word_count for c in draft_chunks),
            chapter_count=len(draft_chunks),
            source_count=len(final_state.get("approved_sources", [])),
            claim_count=len(final_state.get("claims", [])),
            content=content,
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
    """
    async def generate() -> AsyncGenerator[str, None]:
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
            ):
                yield f"data: {json.dumps(progress)}\n\n"

            yield f"data: {json.dumps({'status': 'complete'})}\n\n"

        except Exception as e:
            logger.error(f"Streaming generation failed: {e}")
            yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/health")
async def health_check():
    """Check if the generation service is healthy."""
    return {"status": "healthy", "service": "content-generation"}
