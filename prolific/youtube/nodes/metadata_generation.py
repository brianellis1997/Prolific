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

    # Pull recent titles for DO-NOT-REPEAT. Without past-title awareness the LLM
    # converges on the same mode-appropriate stem across consecutive videos —
    # 5/8 and 5/14 both shipped as "The Forgotten Epoch Before Civilization"
    # despite having different topics, entities, and scripts. The dedup gate at
    # topic-selection time can't catch this because it fires BEFORE the title
    # is written; the LLM picks the duplicate stem here, downstream of all gates.
    recent_titles: list[tuple[str, str]] = []
    try:
        from prolific.youtube.services.channel_history import get_channel_history_service
        history_service = get_channel_history_service()
        await history_service.initialize()
        recent_titles = await history_service.get_recent_titles(limit=14)
    except Exception as exc:
        logger.warning(f"Could not load recent titles (non-fatal): {exc}")

    recent_titles_block = ""
    if recent_titles:
        lines = [f'  - "{t}"' for t, _ in recent_titles]
        recent_titles_block = (
            "\n\n═══ RECENT TITLES ON THIS CHANNEL — DO NOT REUSE THE PRIMARY STEM ═══\n"
            "The last 14 videos shipped with these titles. Your new title MUST have a\n"
            "different primary stem from EVERY one of these (ignoring the channel suffix\n"
            "like '| Sleep Documentary' or '| Sleep History Narration'). Reusing the same\n"
            "stem across videos makes the channel look like a knockoff series — viewers\n"
            "scrolling the channel page will see two videos with identical big text.\n"
            + "\n".join(lines)
        )

    # Reuse the competitor block built once in topic_selection_node — same
    # "what's hot in the niche right now" snapshot the brainstorm saw. Without
    # this, the title LLM is generating titles in a vacuum compared to brainstorm.
    competitor_block = state.get("competitor_inspiration") or ""
    competitor_block_for_prompt = ""
    if competitor_block:
        competitor_block_for_prompt = "\n\n" + competitor_block

    from prolific.youtube.prompts import TITLE_FORMATTING_RULES
    prompt = METADATA_SYSTEM.format(
        topic=topic,
        is_biography=is_biography,
        content_mode=content_mode,
        duration_hours=f"{duration_hours:.1f}",
        section_titles=section_titles_with_timestamps,
        title_patterns=title_patterns,
    ) + continuation_instruction + recent_titles_block + competitor_block_for_prompt + "\n\n" + TITLE_FORMATTING_RULES

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the YouTube metadata now."),
        ],
        output_schema=MetadataResult,
        tier="research",
        temperature=0.5,
    )

    # Post-LLM check: even with the DO-NOT-REPEAT block, the LLM occasionally
    # still produces a dupe stem (especially for LOSTCIV-mode videos which all
    # share a "lost mystery" frame). title_stems_clash catches both exact
    # equality AND prefix-match (e.g. new "The Forgotten Epoch" vs past
    # "The Forgotten Epoch: The Younger Dryas Catastrophe" — different stems
    # after normalization but identical first 4 words = same brand reuse).
    from prolific.services.topic_dedup import normalize_title, title_stems_clash
    new_stem = normalize_title(result.title)
    past_stems = {normalize_title(t): t for t, _ in recent_titles}
    clashing = title_stems_clash(new_stem, past_stems)
    if clashing:
        logger.warning(
            "TITLE DUPE — '%s' normalizes to same stem as past '%s'. Retrying.",
            result.title, clashing,
        )
        retry_prompt = (
            prompt
            + f"\n\n═══ YOUR PREVIOUS ATTEMPT WAS A DUPLICATE ═══\n"
            f"You returned: \"{result.title}\"\n"
            f"This is functionally identical to past video \"{clashing}\" after stripping\n"
            f"the channel suffix. Your NEXT attempt MUST use a primary stem with at least\n"
            f"one substantive content word different. Anchor it to THIS topic — '{topic}'\n"
            f"— with specific nouns the past video didn't use."
        )
        retry_result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=retry_prompt),
                HumanMessage(content="Generate a different title now."),
            ],
            output_schema=MetadataResult,
            tier="research",
            temperature=0.8,
        )
        retry_clash = title_stems_clash(normalize_title(retry_result.title), past_stems)
        if not retry_clash:
            logger.info("TITLE DUPE resolved on retry: '%s'", retry_result.title)
            result = retry_result
        else:
            logger.error(
                "TITLE DUPE PERSISTED after retry — shipping '%s' anyway; manual review needed.",
                retry_result.title,
            )
            result = retry_result

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
