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
        total_secs = int(cumulative)
        hours = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        if hours > 0:
            timestamp_lines.append(f"{hours}:{mins:02d}:{secs:02d} - {s.title}")
        else:
            timestamp_lines.append(f"{mins:02d}:{secs:02d} - {s.title}")
        cumulative += duration_by_section.get(s.section_number, 0)

    section_titles_with_timestamps = "\n".join(timestamp_lines)

    llm_service = get_llm_service()

    # Continuation: if this is an intentional Part 2, look up the parent video
    # title and pass an instruction to enforce a "Part 2" / continuation marker
    # in the new title.
    continuation_instruction = ""
    is_continuation = state.get("is_intentional_continuation", False)
    parent_video_id = state.get("continues_video_id")
    if is_continuation and parent_video_id:
        try:
            from prolific.youtube.services.channel_history import get_channel_history_service
            history_service = get_channel_history_service()
            await history_service.initialize()
            parent = await history_service.get_video_by_id(parent_video_id)
            parent_title = parent.title if parent else ""
        except Exception as exc:
            logger.warning(f"Continuation parent lookup failed (non-fatal): {exc}")
            parent_title = ""

        if parent_title:
            continuation_instruction = (
                f"\n\nIMPORTANT — CONTINUATION VIDEO: This video is a deliberate Part 2 of a "
                f"previous video titled '{parent_title}'. The title MUST include 'Part 2' or "
                f"an equivalent continuation marker (e.g., 'Continued', 'Part II') so viewers "
                f"know it builds on the original. Otherwise structure normally."
            )
        else:
            continuation_instruction = (
                "\n\nIMPORTANT — CONTINUATION VIDEO: This is a deliberate Part 2 of a previous "
                "video. Title MUST include 'Part 2' so viewers know it's a continuation."
            )

    from prolific.youtube.prompts import MODE_TITLE_PATTERNS
    content_mode = state.get("content_mode") or "BIOGRAPHY"
    title_patterns = MODE_TITLE_PATTERNS.get(content_mode, MODE_TITLE_PATTERNS["BIOGRAPHY"])

    prompt = METADATA_SYSTEM.format(
        topic=topic,
        is_biography=is_biography,
        content_mode=content_mode,
        duration_hours=f"{duration_hours:.1f}",
        section_titles=section_titles_with_timestamps,
        title_patterns=title_patterns,
    ) + continuation_instruction

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the YouTube metadata now."),
        ],
        output_schema=MetadataResult,
        tier="research",
        temperature=0.5,
    )

    # Belt-and-suspenders: if continuation flag is set but title doesn't include
    # a Part 2 marker, append one.
    if is_continuation:
        title_lower = result.title.lower()
        markers = ["part 2", "part ii", "part two", "continued", "part 3", "part iii"]
        if not any(m in title_lower for m in markers):
            logger.warning(
                "Continuation flag set but title missing Part 2 marker — appending fallback"
            )
            result.title = f"{result.title} (Part 2)"

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
