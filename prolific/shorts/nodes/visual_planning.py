"""Visual planning node - decides visual segments, aware of source clips."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class VisualSegmentPlan(BaseModel):
    sequence_number: int
    asset_type: str = "web_image"
    search_query: str = ""
    image_prompt: str = ""
    ken_burns_direction: str = "zoom_in"
    duration_weight: float = 1.0
    script_text: str = ""


class VisualPlanResult(BaseModel):
    segments: list[VisualSegmentPlan] = Field(default_factory=list)


async def visual_planning_node(state: ShortsPipelineState) -> dict:
    """Plan visual segments for the short."""
    logger.info("=== SHORTS: VISUAL PLANNING ===")

    content_mode = state.get("content_mode", "news_commentary")

    script = state.get("script")
    if not script:
        return {"errors": ["No script available for visual planning"], "current_phase": "failed"}

    llm_service = get_llm_service()

    from prolific.shorts.prompts import VISUAL_PLANNING_SYSTEM

    topic_type = state.get("topic_type", "")
    topic = state.get("topic", "")
    extra_guidance = ""
    if topic_type == "breaking_news":
        extra_guidance = (
            f"\n\nNOTE: This is a BREAKING NEWS topic about '{topic}'. "
            "Strongly prefer web_image for segments showing real people or events involved."
        )

    existing_source_clips = [
        a for a in state.get("visual_assets", [])
        if a.asset_type == "source_clip" and a.file_path
    ]
    if existing_source_clips:
        clip_info = []
        understandings = state.get("clip_content_understanding") or []
        for i, sc in enumerate(existing_source_clips):
            desc = f"Source clip {i+1} ({sc.duration_seconds:.0f}s): {sc.search_query}"
            if i < len(understandings) and understandings[i].visual_analysis:
                desc += f" - shows: {understandings[i].visual_analysis.visual_summary[:100]}"
            clip_info.append(desc)

        extra_guidance += (
            f"\n\nSOURCE CLIPS AVAILABLE (use asset_type='source_clip' for these):\n"
            + "\n".join(f"- {c}" for c in clip_info)
            + "\n\nIMPORTANT: You have source clips available. Use them for 2-4 segments "
            "(the most dramatic/relevant moments), but ALSO plan web_image segments for "
            "the people, context, and b-roll. A good mix is ~40% source_clip, ~60% web_image. "
            "Do NOT use only source clips -- interleave them with real images of the people involved."
        )

    prompt = VISUAL_PLANNING_SYSTEM.format(
        script_text=script.full_text,
        visual_suggestions="\n".join(f"- {s}" for s in script.visual_suggestions),
    ) + extra_guidance

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Plan the visual segments now."),
        ],
        output_schema=VisualPlanResult,
        tier="research",
        temperature=0.5,
    )

    target_duration = settings.shorts_target_duration_seconds
    segments = result.segments or []
    total_weight = sum(max(0.5, s.duration_weight) for s in segments) or 1.0

    source_clip_files = {}
    for sc in existing_source_clips:
        if sc.file_path:
            source_clip_files[sc.sequence_number] = sc.file_path
    default_source_file = next(iter(source_clip_files.values()), None) if source_clip_files else None

    valid_types = {"stock_clip", "web_image", "source_clip"}
    visual_assets = []
    for seg in segments:
        asset_type = seg.asset_type if seg.asset_type in valid_types else "web_image"
        weight = max(0.5, seg.duration_weight)
        duration = round((weight / total_weight) * target_duration, 1)
        duration = max(2.0, duration)

        file_path = None
        if asset_type == "source_clip":
            file_path = source_clip_files.get(seg.sequence_number, default_source_file)
            if not file_path:
                asset_type = "web_image"

        asset = VisualAsset(
            sequence_number=seg.sequence_number,
            asset_type=asset_type,
            search_query=seg.search_query,
            image_prompt=seg.image_prompt,
            file_path=file_path,
            duration_seconds=duration,
            ken_burns_direction=seg.ken_burns_direction,
            script_text=seg.script_text,
        )
        visual_assets.append(asset)

    stock_count = sum(1 for a in visual_assets if a.asset_type == "stock_clip")
    web_count = sum(1 for a in visual_assets if a.asset_type == "web_image")
    source_count = sum(1 for a in visual_assets if a.asset_type == "source_clip")
    logger.info(f"Planned {len(visual_assets)} visuals: {stock_count} stock, {web_count} web, {source_count} source")

    return {
        "visual_assets": visual_assets,
        "current_phase": "asset_generation",
        "messages": [AIMessage(content=f"Planned {len(visual_assets)} visuals ({stock_count} stock + {web_count} web + {source_count} source)")],
    }
