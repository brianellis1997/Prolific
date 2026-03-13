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
    asset_type: str = "ai_image"
    search_query: str = ""
    image_prompt: str = ""
    ken_burns_direction: str = "zoom_in"


class VisualPlanResult(BaseModel):
    segments: list[VisualSegmentPlan] = Field(default_factory=list)


async def visual_planning_node(state: ShortsPipelineState) -> dict:
    """Plan visual segments for the short."""
    logger.info("=== SHORTS: VISUAL PLANNING ===")

    script = state.get("script")
    if not script:
        return {"errors": ["No script available for visual planning"], "current_phase": "failed"}

    llm_service = get_llm_service()
    num_visuals = settings.shorts_num_visuals

    from prolific.shorts.prompts import VISUAL_PLANNING_SYSTEM

    prompt = VISUAL_PLANNING_SYSTEM.format(
        num_visuals=num_visuals,
        script_text=script.full_text,
        visual_suggestions="\n".join(f"- {s}" for s in script.visual_suggestions),
    )

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
    num_segments = len(result.segments) or num_visuals
    duration_per = target_duration / num_segments

    visual_assets = []
    for seg in result.segments[:num_visuals]:
        asset = VisualAsset(
            sequence_number=seg.sequence_number,
            asset_type="stock_clip" if seg.asset_type == "stock_clip" else "ai_image",
            search_query=seg.search_query,
            image_prompt=seg.image_prompt,
            duration_seconds=duration_per,
            ken_burns_direction=seg.ken_burns_direction,
        )
        visual_assets.append(asset)

    stock_count = sum(1 for a in visual_assets if a.asset_type == "stock_clip")
    image_count = len(visual_assets) - stock_count
    logger.info(f"Planned {len(visual_assets)} visuals: {stock_count} stock clips, {image_count} AI images")

    return {
        "visual_assets": visual_assets,
        "current_phase": "asset_generation",
        "messages": [AIMessage(content=f"Planned {len(visual_assets)} visuals ({stock_count} stock + {image_count} AI)")],
    }
