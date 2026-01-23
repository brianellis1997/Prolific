"""Visual Planner node for determining where visuals are needed.

The Visual Planner Agent analyzes chapter briefs and content to decide
where images, plots, or diagrams would enhance the content.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import VisualIntent, VisualPurpose, VisualType
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class VisualRecommendation(BaseModel):
    """A recommended visual for a chapter section."""

    visual_type: str
    purpose: str
    description: str
    search_queries: list[str] = Field(default_factory=list)
    placement: str = ""
    priority: str = "recommended"


class ChapterVisualPlan(BaseModel):
    """Visual plan for a single chapter."""

    chapter_number: int
    recommendations: list[VisualRecommendation] = Field(default_factory=list)


class VisualPlanResult(BaseModel):
    """Result of visual planning for all chapters."""

    chapter_plans: list[ChapterVisualPlan] = Field(default_factory=list)


VISUAL_PLANNER_PROMPT = """You are a visual content strategist helping to plan illustrations, charts, and images for written content.

Analyze the following chapter briefs and determine where visual elements would enhance understanding and engagement.

Content Style: {style}
Target Audience: {audience}

Consider adding visuals when:
1. Data or statistics are presented (charts/plots)
2. Complex concepts need illustration (diagrams)
3. Comparisons are made (comparison charts, tables)
4. Processes or workflows are described (flowcharts)
5. Abstract ideas could benefit from imagery (illustrations)
6. Breaking up long text sections (relevant images)

For each visual, specify:
- visual_type: "plot" for data, "diagram" for processes, "image_web" for stock/retrieved images
- purpose: "explain", "compare", "show_trend", "illustrate", or "evidence"
- description: What the visual should show
- search_queries: 2-3 queries to find or generate the visual
- placement: Where in the chapter (e.g., "after introduction", "with statistics section")
- priority: "required" for essential visuals, "recommended" for helpful ones, "optional" for nice-to-have

Limit to 1-3 visuals per chapter. Focus on quality over quantity.

Chapter Briefs:
{chapter_briefs}
"""


async def visual_planner_node(state: ContentGenerationState) -> dict:
    """Plan visual elements for chapters.

    This node:
    1. Analyzes chapter briefs for visual opportunities
    2. Creates VisualIntent artifacts specifying needed visuals
    3. Prioritizes visuals based on content needs

    Args:
        state: Current workflow state

    Returns:
        Dict with visual_intents to merge into state
    """
    logger.info("=== VISUAL PLANNING PHASE ===")

    chapter_briefs = state.get("chapter_briefs", [])
    global_memory = state.get("global_memory")

    if not chapter_briefs:
        logger.info("No chapter briefs to plan visuals for")
        return {
            "messages": [AIMessage(content="No chapters to plan visuals for.")],
        }

    style = "academic"
    if global_memory and global_memory.style_guide:
        style = global_memory.style_guide.tone

    audience = "general"
    if state.get("depth") == "technical" or state.get("depth") == "deep":
        audience = "technical"

    briefs_text = "\n\n".join(
        f"**Chapter {b.chapter_number}: {b.title}**\n"
        f"Thesis: {b.thesis_statement}\n"
        f"Key Points: {', '.join(b.key_points[:5])}\n"
        f"Target Words: {b.word_count_target}"
        for b in chapter_briefs[:10]
    )

    llm_service = get_llm_service()

    system_message = SystemMessage(
        content=VISUAL_PLANNER_PROMPT.format(
            style=style,
            audience=audience,
            chapter_briefs=briefs_text,
        )
    )

    user_message = HumanMessage(
        content="Create a visual plan for these chapters. Return structured recommendations."
    )

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=[system_message, user_message],
            output_schema=VisualPlanResult,
            tier="research",
            temperature=0.5,
        )
    except Exception as e:
        logger.warning(f"Visual planning failed: {e}")
        return {
            "messages": [AIMessage(content="Visual planning skipped due to error.")],
        }

    visual_intents = []

    type_mapping = {
        "plot": VisualType.PLOT,
        "diagram": VisualType.DIAGRAM,
        "image_web": VisualType.IMAGE_WEB,
        "image_generated": VisualType.IMAGE_GENERATED,
        "table": VisualType.TABLE,
    }

    purpose_mapping = {
        "explain": VisualPurpose.EXPLAIN,
        "compare": VisualPurpose.COMPARE,
        "show_trend": VisualPurpose.SHOW_TREND,
        "illustrate": VisualPurpose.ILLUSTRATE,
        "evidence": VisualPurpose.EVIDENCE,
    }

    brief_by_number = {b.chapter_number: b for b in chapter_briefs}

    for chapter_plan in result.chapter_plans:
        brief = brief_by_number.get(chapter_plan.chapter_number)
        if not brief:
            continue

        for rec in chapter_plan.recommendations[:3]:
            visual_type = type_mapping.get(rec.visual_type.lower(), VisualType.IMAGE_WEB)
            purpose = purpose_mapping.get(rec.purpose.lower(), VisualPurpose.ILLUSTRATE)

            intent = VisualIntent(
                id=uuid4(),
                chapter_id=brief.chapter_id,
                section_index=0,
                placement_hint=rec.placement,
                visual_type=visual_type,
                purpose=purpose,
                description=rec.description,
                search_queries=rec.search_queries,
                priority=rec.priority if rec.priority in ["required", "recommended", "optional"] else "recommended",
            )
            visual_intents.append(intent)

    logger.info(f"Visual planning complete: {len(visual_intents)} visuals planned")

    return {
        "visual_intents": visual_intents,
        "messages": [
            AIMessage(content=f"Planned {len(visual_intents)} visuals across chapters.")
        ],
    }
