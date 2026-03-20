"""Fair use attribution text generation for source clips."""

import logging

from prolific.shorts.schemas import SourceClip

logger = logging.getLogger(__name__)

FAIR_USE_DISCLAIMER = (
    "This video contains clips used under fair use for commentary, "
    "criticism, and educational purposes (17 U.S.C. Section 107). "
    "No copyright infringement is intended."
)


def generate_attribution(source_clips: list[SourceClip]) -> str:
    """Generate attribution text for YouTube description."""
    if not source_clips:
        return ""

    lines = ["\n---", "Credits:"]
    for clip in source_clips:
        parts = []
        if clip.creator_name:
            parts.append(clip.creator_name)
        if clip.clip_title:
            parts.append(f'"{clip.clip_title}"')
        if clip.platform and clip.platform != "other":
            parts.append(f"({clip.platform.capitalize()})")
        if clip.original_url:
            parts.append(f"- {clip.original_url}")
        if parts:
            lines.append(f"  {' '.join(parts)}")

    lines.append("")
    lines.append(FAIR_USE_DISCLAIMER)
    return "\n".join(lines)
