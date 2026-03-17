"""Visual planning node - decides stock clip vs AI image for each segment."""

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


class VisualPlanResult(BaseModel):
    segments: list[VisualSegmentPlan] = Field(default_factory=list)


async def visual_planning_node(state: ShortsPipelineState) -> dict:
    """Plan visual segments for the short."""
    logger.info("=== SHORTS: VISUAL PLANNING ===")

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

    valid_types = {"stock_clip", "web_image"}
    visual_assets = []
    for seg in segments:
        asset_type = seg.asset_type if seg.asset_type in valid_types else "web_image"
        weight = max(0.5, seg.duration_weight)
        duration = round((weight / total_weight) * target_duration, 1)
        duration = max(2.0, duration)
        asset = VisualAsset(
            sequence_number=seg.sequence_number,
            asset_type=asset_type,
            search_query=seg.search_query,
            image_prompt=seg.image_prompt,
            duration_seconds=duration,
            ken_burns_direction=seg.ken_burns_direction,
        )
        visual_assets.append(asset)

    stock_count = sum(1 for a in visual_assets if a.asset_type == "stock_clip")
    web_count = sum(1 for a in visual_assets if a.asset_type == "web_image")
    ai_count = len(visual_assets) - stock_count - web_count
    logger.info(f"Planned {len(visual_assets)} visuals: {stock_count} stock, {web_count} web, {ai_count} AI")

    return {
        "visual_assets": visual_assets,
        "current_phase": "asset_generation",
        "messages": [AIMessage(content=f"Planned {len(visual_assets)} visuals ({stock_count} stock + {web_count} web + {ai_count} AI)")],
    }
