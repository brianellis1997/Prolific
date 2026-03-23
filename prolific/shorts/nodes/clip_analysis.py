"""Clip analysis node - analyzes downloaded clips to understand their content."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def clip_analysis_node(state: ShortsPipelineState) -> dict:
    """Analyze source clips to understand their content before script writing."""
    logger.info("=== SHORTS: CLIP ANALYSIS ===")

    source_clips = state.get("source_clips", [])
    if not source_clips:
        logger.info("No source clips to analyze")
        return {
            "current_phase": "script_writing",
            "messages": [AIMessage(content="No clips to analyze")],
        }

    output_dir = str(Path(settings.shorts_output_dir) / state["thread_id"])
    topic = state.get("topic", "")

    from prolific.shorts.services.clip_analysis import build_content_understanding

    understandings = []
    for clip in source_clips:
        if not clip.file_path:
            continue

        logger.info(f"Analyzing clip [{clip.sequence_number}]: {clip.clip_title or clip.original_url}")

        understanding = await build_content_understanding(
            clip_path=clip.file_path,
            clip_url=clip.original_url,
            output_dir=output_dir,
            topic=topic,
        )
        understandings.append(understanding)

        if understanding.visual_analysis:
            va = understanding.visual_analysis
            logger.info(f"  People: {', '.join(va.people_visible) or 'none identified'}")
            logger.info(f"  Setting: {va.setting}")
            logger.info(f"  Summary: {va.visual_summary[:100]}")
        if understanding.key_moments:
            for km in understanding.key_moments[:3]:
                logger.info(f"  Moment: {km}")

    relevant_clips = []
    relevant_understandings = []
    topic_lower = topic.lower()
    topic_words = set(topic_lower.split())

    for clip, understanding in zip(source_clips, understandings):
        if not clip.file_path:
            continue
        summary = (understanding.content_summary or "").lower()
        transcript = (understanding.transcript or "").lower()
        title = (clip.clip_title or "").lower()
        combined_text = f"{summary} {transcript} {title}"

        overlap = sum(1 for w in topic_words if len(w) > 3 and w in combined_text)
        relevant = overlap >= 2 or any(
            creator.lower() in combined_text
            for creator in topic_lower.split() if len(creator) > 3
        )

        if relevant:
            relevant_clips.append(clip)
            relevant_understandings.append(understanding)
            logger.info(f"  [{clip.sequence_number}] RELEVANT to topic (matched {overlap} words)")
        else:
            logger.warning(f"  [{clip.sequence_number}] NOT relevant to topic: {understanding.content_summary[:60]}")

    if relevant_clips:
        source_clips_out = relevant_clips
        understandings_out = relevant_understandings
    else:
        logger.warning("No clips matched topic — keeping all clips")
        source_clips_out = [c for c in source_clips if c.file_path]
        understandings_out = understandings

    summary_parts = []
    for u in understandings_out:
        summary_parts.append(f"Clip ({u.clip_duration_seconds:.0f}s): {u.content_summary[:80]}")

    return {
        "source_clips": source_clips_out,
        "clip_content_understanding": understandings_out,
        "current_phase": "script_writing",
        "messages": [AIMessage(content=f"Analyzed {len(understandings_out)} relevant clips: {'; '.join(summary_parts)}")],
    }
