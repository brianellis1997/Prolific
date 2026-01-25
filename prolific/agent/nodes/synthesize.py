"""Synthesize node for creating hierarchical chapter briefs.

The Synthesis Agent combines verified claims and creates a hierarchical
outline (Parts → Chapters → Sections) that constrains the Writer Agents.
"""

import logging
import math
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import (
    ChapterBrief,
    ChapterOutline,
    ClaimStatus,
    PartOutline,
    SectionBrief,
    SectionOutline,
)
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)

PART_THRESHOLD = 50000
TARGET_CHAPTER_WORDS = 6000
TARGET_SECTION_WORDS = 2000
MIN_CHAPTERS = 3
MAX_CHAPTERS = 25
MIN_SECTIONS_PER_CHAPTER = 2
MAX_SECTIONS_PER_CHAPTER = 5


class SectionPlan(BaseModel):
    """Plan for a single section."""

    title: str
    key_points: list[str] = Field(default_factory=list)


class ChapterPlan(BaseModel):
    """Plan for a single chapter."""

    title: str
    thesis_statement: str
    sections: list[SectionPlan] = Field(default_factory=list)
    word_count_target: int = 6000


class PartPlan(BaseModel):
    """Plan for a part (major division)."""

    title: str
    theme: str
    chapter_titles: list[str] = Field(default_factory=list)


class HierarchicalOutlineResult(BaseModel):
    """Generated hierarchical outline."""

    parts: list[PartPlan] = Field(default_factory=list)
    chapters: list[ChapterPlan] = Field(default_factory=list)


SYNTHESIS_SYSTEM_PROMPT = """You are a content architect creating a detailed hierarchical outline.

Topic: {topic}
Subtopics: {subtopics}
Target word count: {target_words:,} words (~{page_count} pages)
Depth level: {depth}
Style: {style}

Available verified claims: {claim_count}
Key topics from claims: {claim_topics}

{part_instructions}

For each chapter:
- Target ~{chapter_words:,} words ({sections_per_chapter} sections of ~{section_words:,} words each)
- Clear thesis statement
- {sections_per_chapter} distinct sections, each with 2-4 key points

Create a logical structure that:
1. Flows naturally from introduction to conclusion
2. Groups related content into chapters
3. Each section covers a focused subtopic
4. Builds from foundational to advanced concepts"""


def calculate_structure(target_words: int, depth: str) -> dict:
    """Calculate the hierarchical structure based on target length.

    Args:
        target_words: Target word count
        depth: Depth level (overview, standard, deep, exhaustive)

    Returns:
        Dict with num_parts, num_chapters, sections_per_chapter, etc.
    """
    use_parts = target_words >= PART_THRESHOLD

    if depth == "overview":
        chapter_words = 4000
        sections_per_chapter = 2
    elif depth == "standard":
        chapter_words = 5000
        sections_per_chapter = 3
    elif depth == "deep":
        chapter_words = 6000
        sections_per_chapter = 4
    else:
        chapter_words = 7000
        sections_per_chapter = 5

    num_chapters = max(MIN_CHAPTERS, min(MAX_CHAPTERS, target_words // chapter_words))

    actual_chapter_words = target_words // num_chapters
    actual_section_words = actual_chapter_words // sections_per_chapter

    num_parts = 0
    if use_parts:
        num_parts = min(5, max(2, num_chapters // 4))

    return {
        "use_parts": use_parts,
        "num_parts": num_parts,
        "num_chapters": num_chapters,
        "sections_per_chapter": sections_per_chapter,
        "chapter_words": actual_chapter_words,
        "section_words": actual_section_words,
        "page_count": target_words // 250,
    }


def build_claim_url_map(
    claims: list,
    approved_sources: list,
) -> dict[UUID, str]:
    """Build a mapping from claim IDs to their primary source URLs.

    Args:
        claims: List of Claim objects
        approved_sources: List of ApprovedSource objects

    Returns:
        Dict mapping claim_id -> source_url for hyperlink generation
    """
    source_map = {s.id: s for s in approved_sources}
    claim_url_map = {}

    for claim in claims:
        if claim.source_ids:
            source = source_map.get(claim.source_ids[0])
            if source and source.url:
                claim_url_map[claim.id] = source.url

    return claim_url_map


def assign_claims_to_sections(
    verified_claims: list,
    chapters: list[ChapterPlan],
) -> dict[tuple[int, int], list[UUID]]:
    """Assign claims to specific sections based on topic matching.

    Args:
        verified_claims: List of verified Claim objects
        chapters: List of ChapterPlan objects with sections

    Returns:
        Dict mapping (chapter_idx, section_idx) -> list of claim IDs
    """
    assignments: dict[tuple[int, int], list[UUID]] = {}

    for chapter_idx, chapter in enumerate(chapters):
        for section_idx in range(len(chapter.sections)):
            assignments[(chapter_idx, section_idx)] = []

    for claim in verified_claims:
        best_location = (0, 0)
        best_score = 0

        for chapter_idx, chapter in enumerate(chapters):
            chapter_keywords = set(chapter.title.lower().split())
            chapter_keywords.update(chapter.thesis_statement.lower().split())

            for section_idx, section in enumerate(chapter.sections):
                section_keywords = set(section.title.lower().split())
                for point in section.key_points:
                    section_keywords.update(point.lower().split())

                all_keywords = chapter_keywords | section_keywords
                score = 0

                for tag in claim.topic_tags:
                    tag_lower = tag.lower()
                    if tag_lower in all_keywords:
                        score += 3
                    for keyword in all_keywords:
                        if tag_lower in keyword or keyword in tag_lower:
                            score += 1

                for keyword in section_keywords:
                    score += 0.5

                if score > best_score:
                    best_score = score
                    best_location = (chapter_idx, section_idx)

        assignments[best_location].append(claim.id)

    return assignments


async def synthesize_node(state: ContentGenerationState) -> dict:
    """Synthesize verified claims into hierarchical chapter briefs.

    This node:
    1. Calculates appropriate structure based on target length
    2. Generates hierarchical outline (Parts → Chapters → Sections)
    3. Assigns verified claims to specific sections
    4. Creates ChapterBrief and SectionBrief artifacts
    5. Includes source URLs for inline hyperlink generation

    Args:
        state: Current workflow state

    Returns:
        Dict with hierarchical briefs to merge into state
    """
    logger.info("=== SYNTHESIS PHASE ===")

    claims = state.get("claims", [])
    verified_claims = [c for c in claims if c.status == ClaimStatus.VERIFIED]
    approved_sources = state.get("approved_sources", [])

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
    llm_service = get_llm_service()

    topic_tags = set()
    for claim in verified_claims:
        topic_tags.update(claim.topic_tags)

    target_words = state.get("target_word_count", 50000)
    depth = state.get("depth", "standard")

    structure = calculate_structure(target_words, depth)
    logger.info(
        f"Structure: {structure['num_chapters']} chapters, "
        f"{structure['sections_per_chapter']} sections each, "
        f"~{structure['chapter_words']} words/chapter"
    )
    if structure["use_parts"]:
        logger.info(f"Using {structure['num_parts']} parts for document organization")

    claim_url_map = build_claim_url_map(verified_claims, approved_sources)
    logger.info(f"Built URL map for {len(claim_url_map)} claims (for hyperlinks)")

    style_guide = global_memory.style_guide if global_memory else None
    style_str = style_guide.tone if style_guide else "academic"

    if structure["use_parts"]:
        part_instructions = f"""This is a long document requiring {structure['num_parts']} major parts.
Each part should have a distinct theme and contain 3-6 chapters.
Define the parts first, then detail the chapters within each part."""
    else:
        part_instructions = "No parts needed - organize directly into chapters."

    system_message = SystemMessage(
        content=SYNTHESIS_SYSTEM_PROMPT.format(
            topic=state["topic"],
            subtopics=", ".join(state.get("subtopics", [])),
            target_words=target_words,
            page_count=structure["page_count"],
            depth=depth,
            style=style_str,
            claim_count=len(verified_claims),
            claim_topics=", ".join(list(topic_tags)[:20]),
            part_instructions=part_instructions,
            chapter_words=structure["chapter_words"],
            sections_per_chapter=structure["sections_per_chapter"],
            section_words=structure["section_words"],
        )
    )

    user_message = HumanMessage(
        content=f"""Create a hierarchical outline with {structure['num_chapters']} chapters.

Each chapter should have exactly {structure['sections_per_chapter']} sections.
Target ~{structure['chapter_words']:,} words per chapter.

Ensure:
1. Engaging introduction chapter
2. Logical progression through "{state['topic']}"
3. Each section has focused, specific content
4. Strong conclusion chapter

Return the complete hierarchical structure."""
    )

    logger.info("Generating hierarchical outline (1 LLM call)")

    try:
        outline_result = await llm_service.invoke_with_structured_output(
            messages=[system_message, user_message],
            output_schema=HierarchicalOutlineResult,
            tier="writing",
            temperature=0.5,
        )
    except Exception as e:
        logger.error(f"Outline generation failed: {e}")
        outline_result = HierarchicalOutlineResult(
            chapters=[
                ChapterPlan(
                    title="Introduction",
                    thesis_statement=f"Introduction to {state['topic']}",
                    sections=[
                        SectionPlan(title="Overview", key_points=["Context", "Scope"]),
                        SectionPlan(title="Key Concepts", key_points=["Definitions", "Framework"]),
                    ],
                    word_count_target=structure["chapter_words"],
                ),
                ChapterPlan(
                    title="Main Analysis",
                    thesis_statement=f"Core analysis of {state['topic']}",
                    sections=[
                        SectionPlan(title="Current State", key_points=["Status", "Trends"]),
                        SectionPlan(title="Deep Dive", key_points=["Details", "Evidence"]),
                    ],
                    word_count_target=structure["chapter_words"] * 2,
                ),
                ChapterPlan(
                    title="Conclusion",
                    thesis_statement=f"Summary of {state['topic']}",
                    sections=[
                        SectionPlan(title="Key Findings", key_points=["Summary", "Insights"]),
                        SectionPlan(title="Future Directions", key_points=["Implications", "Next Steps"]),
                    ],
                    word_count_target=structure["chapter_words"],
                ),
            ]
        )

    section_assignments = assign_claims_to_sections(
        verified_claims, outline_result.chapters
    )

    total_assigned = sum(len(claims) for claims in section_assignments.values())
    logger.info(f"Assigned {total_assigned} claims to {len(section_assignments)} sections")

    part_outlines = []
    chapter_outlines = []
    section_outlines = []
    chapter_briefs = []
    section_briefs = []

    if structure["use_parts"] and outline_result.parts:
        for part_idx, part_plan in enumerate(outline_result.parts):
            part = PartOutline(
                id=uuid4(),
                part_number=part_idx + 1,
                title=part_plan.title,
                theme=part_plan.theme,
                chapter_ids=[],
            )
            part_outlines.append(part)

    current_part_idx = 0
    chapters_per_part = (
        len(outline_result.chapters) // len(part_outlines)
        if part_outlines
        else 0
    )

    for chapter_idx, chapter_plan in enumerate(outline_result.chapters):
        part_id = None
        if part_outlines:
            current_part_idx = min(chapter_idx // max(1, chapters_per_part), len(part_outlines) - 1)
            part_id = part_outlines[current_part_idx].id
            part_outlines[current_part_idx].chapter_ids.append(uuid4())

        chapter_outline = ChapterOutline(
            id=uuid4(),
            part_id=part_id,
            chapter_number=chapter_idx + 1,
            title=chapter_plan.title,
            summary=chapter_plan.thesis_statement,
            key_topics=[s.title for s in chapter_plan.sections],
            estimated_word_count=chapter_plan.word_count_target,
            section_ids=[],
        )
        chapter_outlines.append(chapter_outline)

        chapter_claims = []
        chapter_section_briefs = []

        for section_idx, section_plan in enumerate(chapter_plan.sections):
            section_id = uuid4()
            chapter_outline.section_ids.append(section_id)

            section_claim_ids = section_assignments.get((chapter_idx, section_idx), [])
            chapter_claims.extend(section_claim_ids)

            section_url_map = {
                str(cid): claim_url_map.get(cid, "")
                for cid in section_claim_ids
                if cid in claim_url_map
            }

            section_word_target = chapter_plan.word_count_target // len(chapter_plan.sections)

            section_outline = SectionOutline(
                id=section_id,
                chapter_id=chapter_outline.id,
                section_number=section_idx + 1,
                title=section_plan.title,
                key_points=section_plan.key_points,
                estimated_word_count=section_word_target,
                claim_ids=section_claim_ids,
            )
            section_outlines.append(section_outline)

            section_brief = SectionBrief(
                id=uuid4(),
                section_id=section_id,
                chapter_id=chapter_outline.id,
                section_number=section_idx + 1,
                title=section_plan.title,
                key_points=section_plan.key_points,
                required_claims=section_claim_ids,
                claim_urls=section_url_map,
                word_count_target=section_word_target,
                word_count_min=int(section_word_target * 0.8),
                word_count_max=int(section_word_target * 1.2),
            )
            section_briefs.append(section_brief)
            chapter_section_briefs.append(section_brief)

        required_count = len(chapter_claims) // 2 + 1
        required_claims = chapter_claims[:required_count]
        optional_claims = chapter_claims[required_count:]

        chapter_brief = ChapterBrief(
            id=uuid4(),
            chapter_id=chapter_outline.id,
            part_id=part_id,
            chapter_number=chapter_idx + 1,
            title=chapter_plan.title,
            thesis_statement=chapter_plan.thesis_statement,
            required_claims=required_claims,
            optional_claims=optional_claims,
            key_points=[s.title for s in chapter_plan.sections],
            section_briefs=chapter_section_briefs,
            word_count_target=chapter_plan.word_count_target,
            word_count_min=int(chapter_plan.word_count_target * 0.8),
            word_count_max=int(chapter_plan.word_count_target * 1.2),
        )
        chapter_briefs.append(chapter_brief)

    if global_memory:
        global_memory.outline_ids = [o.id for o in chapter_outlines]
        global_memory.chapter_order = [o.id for o in chapter_outlines]

    logger.info(
        f"Synthesis complete: {len(part_outlines)} parts, "
        f"{len(chapter_briefs)} chapters, {len(section_briefs)} sections"
    )

    return {
        "part_outlines": part_outlines,
        "chapter_outlines": chapter_outlines,
        "section_outlines": section_outlines,
        "chapter_briefs": chapter_briefs,
        "section_briefs": section_briefs,
        "global_memory": global_memory,
        "current_phase": "write",
        "synthesis_complete": True,
        "messages": [
            AIMessage(
                content=f"Created hierarchical outline: {len(part_outlines)} parts, "
                f"{len(chapter_briefs)} chapters, {len(section_briefs)} sections."
            )
        ],
    }
