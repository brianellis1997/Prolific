"""LangGraph state definition with reducers for the content generation workflow.

The state is the central data structure that flows through the entire workflow.
Reducers handle merging results from parallel agent execution.
"""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage

from prolific.schemas.artifacts import (
    ApprovedSource,
    ChapterBrief,
    ChapterOutline,
    Claim,
    ContentGap,
    DraftChunk,
    EvidenceSnippet,
    PartOutline,
    QualityIssue,
    SectionBrief,
    SectionOutline,
    SourceCandidate,
    VisualAsset,
    VisualIntent,
)
from prolific.schemas.memory import GlobalBookMemory, LocalChapterMemory


def merge_artifacts_by_id[T](left: list[T], right: list[T]) -> list[T]:
    """Reducer that merges lists by ID, with right items updating left items.

    Used for artifact lists where each item has a unique ID.
    Right items with matching IDs replace left items (to support updates).
    """
    items_by_id = {}
    items_without_id = []

    for item in left:
        item_id = getattr(item, "id", None)
        if item_id is not None:
            items_by_id[item_id] = item
        else:
            items_without_id.append(item)

    for item in right:
        item_id = getattr(item, "id", None)
        if item_id is not None:
            items_by_id[item_id] = item
        else:
            items_without_id.append(item)

    return list(items_by_id.values()) + items_without_id


def merge_dicts[K, V](left: dict[K, V], right: dict[K, V]) -> dict[K, V]:
    """Reducer that merges dictionaries, with right taking precedence."""
    result = dict(left)
    result.update(right)
    return result


def replace_value[T](left: T, right: T) -> T:
    """Reducer that simply replaces the value (last write wins)."""
    return right


class ContentGenerationState(TypedDict):
    """Main state for the content generation workflow.

    This state flows through all nodes in the LangGraph.
    Annotated fields use reducers to handle parallel execution merging.
    """

    # === INPUT PARAMETERS ===
    topic: str
    subtopics: list[str]
    focus_areas: list[str]
    target_word_count: int
    depth: str  # "overview", "standard", "deep", "exhaustive"
    style_preferences: dict[str, str]

    # === THREAD ISOLATION ===
    thread_id: str  # Unique ID to isolate RAG data between generations

    # === MESSAGES (for agent communication history) ===
    messages: Annotated[list[BaseMessage], operator.add]

    # === ARTIFACTS (accumulated across workflow) ===
    source_candidates: Annotated[list[SourceCandidate], merge_artifacts_by_id]
    approved_sources: Annotated[list[ApprovedSource], merge_artifacts_by_id]
    evidence_snippets: Annotated[list[EvidenceSnippet], merge_artifacts_by_id]
    claims: Annotated[list[Claim], merge_artifacts_by_id]

    # === HIERARCHICAL STRUCTURE ===
    part_outlines: Annotated[list[PartOutline], merge_artifacts_by_id]
    chapter_outlines: Annotated[list[ChapterOutline], merge_artifacts_by_id]
    section_outlines: Annotated[list[SectionOutline], merge_artifacts_by_id]
    chapter_briefs: Annotated[list[ChapterBrief], merge_artifacts_by_id]
    section_briefs: Annotated[list[SectionBrief], merge_artifacts_by_id]

    draft_chunks: Annotated[list[DraftChunk], merge_artifacts_by_id]
    content_gaps: Annotated[list[ContentGap], merge_artifacts_by_id]

    # === VISUAL ARTIFACTS ===
    visual_intents: Annotated[list[VisualIntent], merge_artifacts_by_id]
    visual_assets: Annotated[list[VisualAsset], merge_artifacts_by_id]
    quality_issues: Annotated[list[QualityIssue], merge_artifacts_by_id]

    # === MEMORY ===
    global_memory: Annotated[GlobalBookMemory, replace_value]
    local_memories: Annotated[dict[str, LocalChapterMemory], merge_dicts]

    # === WORKFLOW CONTROL ===
    current_phase: str  # Current workflow phase
    current_chapter_index: int
    iteration_count: int
    max_iterations: int
    remediation_count: int  # Number of quality remediation passes

    # === STATUS FLAGS ===
    research_complete: bool
    verification_complete: bool
    extraction_complete: bool
    synthesis_complete: bool
    writing_complete: bool
    integration_complete: bool
    needs_replan: bool
    needs_remediation: bool  # True if quality issues need remediation

    # === SOURCE TRACKING ===
    source_shortage: bool  # True if approved sources < target
    source_shortage_amount: int  # How many sources below target
    source_target: int  # Target number of sources based on depth/word count

    # === ERROR HANDLING ===
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]


def create_initial_state(
    topic: str,
    subtopics: list[str] | None = None,
    focus_areas: list[str] | None = None,
    target_word_count: int = 50000,
    depth: str = "standard",
    style_preferences: dict[str, str] | None = None,
    max_iterations: int = 5,
    thread_id: str | None = None,
) -> ContentGenerationState:
    """Create initial state for a new content generation run.

    Args:
        topic: Main topic for the content
        subtopics: List of subtopics to cover
        focus_areas: Specific areas to focus on
        target_word_count: Target length in words
        depth: Depth level (overview, standard, deep, exhaustive)
        style_preferences: Writing style preferences
        max_iterations: Maximum research-write iterations
        thread_id: Unique thread ID for RAG isolation (generated if None)

    Returns:
        Initial ContentGenerationState ready for workflow
    """
    from uuid import uuid4
    if thread_id is None:
        thread_id = str(uuid4())
    from prolific.schemas.memory import StyleGuide

    style_guide = StyleGuide()
    if style_preferences:
        if "tone" in style_preferences:
            style_guide.tone = style_preferences["tone"]
        if "citation_style" in style_preferences:
            style_guide.citation_style = style_preferences["citation_style"]

    global_memory = GlobalBookMemory(
        title=topic,
        target_word_count=target_word_count,
        depth_level=depth,
        style_guide=style_guide,
        topics_remaining=set(subtopics or []),
    )

    return ContentGenerationState(
        topic=topic,
        subtopics=subtopics or [],
        focus_areas=focus_areas or [],
        target_word_count=target_word_count,
        depth=depth,
        style_preferences=style_preferences or {},
        thread_id=thread_id,
        messages=[],
        source_candidates=[],
        approved_sources=[],
        evidence_snippets=[],
        claims=[],
        part_outlines=[],
        chapter_outlines=[],
        section_outlines=[],
        chapter_briefs=[],
        section_briefs=[],
        draft_chunks=[],
        content_gaps=[],
        visual_intents=[],
        visual_assets=[],
        quality_issues=[],
        global_memory=global_memory,
        local_memories={},
        current_phase="research",
        current_chapter_index=0,
        iteration_count=0,
        max_iterations=max_iterations,
        remediation_count=0,
        research_complete=False,
        verification_complete=False,
        extraction_complete=False,
        synthesis_complete=False,
        writing_complete=False,
        integration_complete=False,
        needs_replan=False,
        needs_remediation=False,
        source_shortage=False,
        source_shortage_amount=0,
        source_target=10,
        errors=[],
        warnings=[],
    )
