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

    summary_parts = []
    for u in understandings:
        summary_parts.append(f"Clip ({u.clip_duration_seconds:.0f}s): {u.content_summary[:80]}")

    return {
        "clip_content_understanding": understandings,
        "current_phase": "script_writing",
        "messages": [AIMessage(content=f"Analyzed {len(understandings)} clips: {'; '.join(summary_parts)}")],
    }
