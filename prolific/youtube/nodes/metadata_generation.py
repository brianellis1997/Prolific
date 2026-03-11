"""Metadata generation node - creates YouTube title, description, tags."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import METADATA_SYSTEM
from prolific.youtube.schemas import VideoMetadata
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


class MetadataResult(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)


async def metadata_generation_node(state: YouTubePipelineState) -> dict:
    """Generate YouTube-optimized metadata."""
    logger.info("=== METADATA GENERATION ===")

    topic = state["topic"]
    is_biography = state.get("is_biography", False)
    sections = state["script_sections"]
    audio_chunks = state["audio_chunks"]

    total_duration = sum(c.duration_seconds for c in audio_chunks)
    duration_hours = total_duration / 3600

    duration_by_section = {c.section_number: c.duration_seconds for c in audio_chunks}
    timestamp_lines = []
    cumulative = 0.0
    for s in sections:
        mins = int(cumulative // 60)
        secs = int(cumulative % 60)
        timestamp_lines.append(f"{mins:02d}:{secs:02d} - {s.title}")
        cumulative += duration_by_section.get(s.section_number, 0)

    section_titles_with_timestamps = "\n".join(timestamp_lines)

    llm_service = get_llm_service()

    prompt = METADATA_SYSTEM.format(
        topic=topic,
        is_biography=is_biography,
        duration_hours=f"{duration_hours:.1f}",
        section_titles=section_titles_with_timestamps,
    )

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the YouTube metadata now."),
        ],
        output_schema=MetadataResult,
        tier="research",
        temperature=0.5,
    )

    from prolific.core.config import settings

    metadata = VideoMetadata(
        title=result.title[:100],
        description=result.description,
        tags=result.tags[:20],
        category_id=settings.youtube_category_id,
        privacy_status=settings.youtube_default_privacy,
    )

    logger.info(f"Title: {metadata.title}")
    logger.info(f"Tags: {len(metadata.tags)}")
    logger.info(f"Description length: {len(metadata.description)} chars")

    return {
        "video_metadata": metadata,
        "current_phase": "youtube_upload",
        "messages": [AIMessage(content=f"Metadata: {metadata.title}")],
    }
