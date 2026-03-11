"""Image planning node - creates image prompts for each section."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import IMAGE_PLANNING_SYSTEM
from prolific.youtube.schemas import ImageAsset
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)

KEN_BURNS_DIRECTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right"]


class ImagePromptEntry(BaseModel):
    section_number: int
    prompt: str
    ken_burns_direction: str = "zoom_in"


class ImagePlanResult(BaseModel):
    images: list[ImagePromptEntry] = Field(default_factory=list)


async def image_planning_node(state: YouTubePipelineState) -> dict:
    """Plan image prompts for each section."""
    logger.info("=== IMAGE PLANNING ===")

    topic = state["topic"]
    sections = state["script_sections"]
    style = settings.youtube_image_style

    llm_service = get_llm_service()

    sections_str = "\n".join(
        f"Section {s.section_number}: {s.title} - {s.content[:200]}..."
        for s in sections
        if s.content
    )

    prompt = IMAGE_PLANNING_SYSTEM.format(topic=topic, style=style)

    plan_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content=f"Script sections:\n{sections_str}\n\nCreate one image prompt per section."),
        ],
        output_schema=ImagePlanResult,
        tier="research",
        temperature=0.5,
    )

    image_assets = []
    for i, entry in enumerate(plan_result.images):
        direction = entry.ken_burns_direction
        if direction not in KEN_BURNS_DIRECTIONS:
            direction = KEN_BURNS_DIRECTIONS[i % len(KEN_BURNS_DIRECTIONS)]

        matching_section = next(
            (s for s in sections if s.section_number == entry.section_number),
            None,
        )
        duration = matching_section.estimated_duration_minutes * 60 if matching_section else 420.0

        asset = ImageAsset(
            section_number=entry.section_number,
            prompt=entry.prompt,
            style=style,
            duration_seconds=duration,
            ken_burns_direction=direction,
        )
        image_assets.append(asset)

    logger.info(f"Planned {len(image_assets)} images")

    return {
        "image_assets": image_assets,
        "current_phase": "image_generation",
        "messages": [AIMessage(content=f"Planned {len(image_assets)} images")],
    }
