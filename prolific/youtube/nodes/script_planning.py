"""Script planning node - creates the section outline for the narration."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import SCRIPT_PLANNING_SYSTEM
from prolific.youtube.schemas import ScriptSection
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE_NARRATION = 150


class PlannedSection(BaseModel):
    title: str
    key_points: list[str] = Field(default_factory=list)
    transition_hint: str = ""


class ScriptPlan(BaseModel):
    sections: list[PlannedSection]


async def script_planning_node(state: YouTubePipelineState) -> dict:
    """Plan the narration script structure."""
    logger.info("=== SCRIPT PLANNING ===")

    topic = state["topic"]
    target_words = settings.youtube_target_word_count
    num_sections = settings.youtube_max_images
    words_per_section = target_words // num_sections
    duration_hours = round(target_words / WORDS_PER_MINUTE_NARRATION / 60, 1)

    logger.info(f"Topic: {topic}")
    logger.info(f"Target: {target_words} words, ~{duration_hours} hours, {num_sections} sections")

    llm_service = get_llm_service()

    prompt = SCRIPT_PLANNING_SYSTEM.format(
        duration=duration_hours,
        topic=topic,
        num_sections=num_sections,
        words_per_section=words_per_section,
    )

    plan_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content=f"Create the outline for: {topic}"),
        ],
        output_schema=ScriptPlan,
        tier="research",
        temperature=0.5,
    )

    sections = []
    for i, planned in enumerate(plan_result.sections):
        section = ScriptSection(
            section_number=i + 1,
            title=planned.title,
            key_points=planned.key_points,
            word_count=0,
            estimated_duration_minutes=words_per_section / WORDS_PER_MINUTE_NARRATION,
        )
        sections.append(section)

    logger.info(f"Planned {len(sections)} sections")
    for s in sections:
        logger.info(f"  Section {s.section_number}: {s.title}")

    return {
        "script_sections": sections,
        "current_phase": "script_writing",
        "messages": [AIMessage(content=f"Planned {len(sections)} sections for {topic}")],
    }
