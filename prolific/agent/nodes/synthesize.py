"""Synthesize node for creating chapter briefs.

The Synthesis Agent combines verified claims and the outline
to create detailed briefs that constrain the Writer Agents.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ChapterBrief, ChapterOutline, ClaimStatus
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class ChapterPlan(BaseModel):
    """Plan for a single chapter."""

    title: str
    thesis_statement: str
    key_points: list[str] = Field(default_factory=list)
    word_count_target: int = 2000


class OutlineResult(BaseModel):
    """Generated outline with chapters."""

    chapters: list[ChapterPlan] = Field(default_factory=list)


SYNTHESIS_SYSTEM_PROMPT = """You are a content architect creating a detailed outline and chapter briefs.

Topic: {topic}
Subtopics: {subtopics}
Target word count: {target_words}
Depth level: {depth}
Style: {style}

Available verified claims: {claim_count}
Key topics from claims: {claim_topics}

Create a logical chapter structure that:
1. Covers all subtopics comprehensively
2. Flows naturally from introduction to conclusion
3. Distributes word count appropriately
4. Organizes claims into relevant chapters

For each chapter, provide:
- Clear title
- Thesis statement (main argument/purpose)
- Key points to cover (3-5 points)
- Target word count"""


async def synthesize_node(state: ContentGenerationState) -> dict:
    """Synthesize verified claims into chapter briefs.

    This node:
    1. Generates outline if not exists
    2. Assigns verified claims to chapters
    3. Creates ChapterBrief artifacts with constraints

    Args:
        state: Current workflow state

    Returns:
        Dict with chapter_briefs and outline to merge into state
    """
    logger.info("=== SYNTHESIS PHASE ===")

    claims = state.get("claims", [])
    verified_claims = [c for c in claims if c.status == ClaimStatus.VERIFIED]

    logger.info(f"Total claims: {len(claims)}, Verified: {len(verified_claims)}")

    if not verified_claims:
        logger.warning("No verified claims available for synthesis")
        return {
            "current_phase": "replan",
            "needs_replan": True,
            "messages": [
                AIMessage(content="No verified claims. Need more research.")
            ],
        }

    global_memory = state.get("global_memory")
    if global_memory and global_memory.outline_ids:
        logger.info("Using existing outline")
    else:
        logger.info("Generating new outline (1 LLM call for outline structure)")

    llm_service = get_llm_service()

    topic_tags = set()
    for claim in verified_claims:
        topic_tags.update(claim.topic_tags)

    target_words = state.get("target_word_count", 50000)
    depth = state.get("depth", "standard")

    if depth == "overview":
        num_chapters = max(3, target_words // 3000)
    elif depth == "standard":
        num_chapters = max(5, target_words // 2500)
    elif depth == "deep":
        num_chapters = max(8, target_words // 2000)
    else:
        num_chapters = max(10, target_words // 1500)

    style_guide = global_memory.style_guide if global_memory else None
    style_str = style_guide.tone if style_guide else "academic"

    system_message = SystemMessage(
        content=SYNTHESIS_SYSTEM_PROMPT.format(
            topic=state["topic"],
            subtopics=", ".join(state.get("subtopics", [])),
            target_words=target_words,
            depth=depth,
            style=style_str,
            claim_count=len(verified_claims),
            claim_topics=", ".join(list(topic_tags)[:20]),
        )
    )

    user_message = HumanMessage(
        content=f"""Create an outline with approximately {num_chapters} chapters.

Ensure the outline:
1. Has an engaging introduction
2. Covers all major aspects of "{state['topic']}"
3. Builds logically from basics to more advanced topics
4. Ends with a strong conclusion

Return the chapter structure."""
    )

    try:
        outline_result = await llm_service.invoke_with_structured_output(
            messages=[system_message, user_message],
            output_schema=OutlineResult,
            tier="writing",
            temperature=0.5,
        )
    except Exception as e:
        logger.error(f"Outline generation failed: {e}")
        outline_result = OutlineResult(
            chapters=[
                ChapterPlan(
                    title="Introduction",
                    thesis_statement=f"Introduction to {state['topic']}",
                    key_points=["Overview", "Key concepts", "Chapter preview"],
                    word_count_target=target_words // num_chapters,
                ),
                ChapterPlan(
                    title="Main Content",
                    thesis_statement=f"Core discussion of {state['topic']}",
                    key_points=state.get("subtopics", ["Main topic"])[:5],
                    word_count_target=target_words * 2 // 3,
                ),
                ChapterPlan(
                    title="Conclusion",
                    thesis_statement=f"Summary and implications of {state['topic']}",
                    key_points=["Summary", "Implications", "Future directions"],
                    word_count_target=target_words // num_chapters,
                ),
            ]
        )

    chapter_outlines = []
    chapter_briefs = []

    claim_assignments = {i: [] for i in range(len(outline_result.chapters))}
    for claim in verified_claims:
        best_chapter = 0
        best_score = 0

        for i, chapter in enumerate(outline_result.chapters):
            score = 0
            chapter_keywords = set(chapter.title.lower().split())
            chapter_keywords.update(
                word.lower() for point in chapter.key_points for word in point.split()
            )

            for tag in claim.topic_tags:
                if tag.lower() in chapter_keywords:
                    score += 2
                for keyword in chapter_keywords:
                    if tag.lower() in keyword or keyword in tag.lower():
                        score += 1

            if score > best_score:
                best_score = score
                best_chapter = i

        claim_assignments[best_chapter].append(claim.id)

    for i, chapter_plan in enumerate(outline_result.chapters):
        outline = ChapterOutline(
            id=uuid4(),
            chapter_number=i + 1,
            title=chapter_plan.title,
            summary=chapter_plan.thesis_statement,
            key_topics=chapter_plan.key_points,
            estimated_word_count=chapter_plan.word_count_target,
        )
        chapter_outlines.append(outline)

        assigned_claims = claim_assignments.get(i, [])
        required_claims = assigned_claims[: len(assigned_claims) // 2 + 1]
        optional_claims = assigned_claims[len(assigned_claims) // 2 + 1:]

        brief = ChapterBrief(
            id=uuid4(),
            chapter_id=outline.id,
            chapter_number=i + 1,
            title=chapter_plan.title,
            thesis_statement=chapter_plan.thesis_statement,
            required_claims=required_claims,
            optional_claims=optional_claims,
            key_points=chapter_plan.key_points,
            word_count_target=chapter_plan.word_count_target,
            word_count_min=int(chapter_plan.word_count_target * 0.8),
            word_count_max=int(chapter_plan.word_count_target * 1.2),
        )
        chapter_briefs.append(brief)

    if global_memory:
        global_memory.outline_ids = [o.id for o in chapter_outlines]
        global_memory.chapter_order = [o.id for o in chapter_outlines]

    logger.info(f"Synthesis complete: {len(chapter_briefs)} chapter briefs created")

    return {
        "chapter_briefs": chapter_briefs,
        "global_memory": global_memory,
        "current_phase": "write",
        "synthesis_complete": True,
        "messages": [
            AIMessage(
                content=f"Created outline with {len(chapter_briefs)} chapters."
            )
        ],
    }
