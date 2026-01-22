"""LangGraph workflow assembly for content generation.

This module assembles all agent nodes into a complete workflow
with routing logic for the research-write-replan loop.
"""

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from prolific.agent.nodes import (
    cross_check_node,
    extract_node,
    integrate_node,
    replan_node,
    research_node,
    summarize_node,
    synthesize_node,
    verify_node,
    write_node,
)
from prolific.agent.state import ContentGenerationState

logger = logging.getLogger(__name__)


def should_continue_after_verify(
    state: ContentGenerationState,
) -> Literal["extract", "replan"]:
    """Route after verification: extract if sources approved, replan if not enough."""
    approved = state.get("approved_sources", [])
    if len(approved) >= 3:
        return "extract"
    else:
        logger.warning("Not enough approved sources, replanning")
        return "replan"


def should_continue_after_synthesize(
    state: ContentGenerationState,
) -> Literal["write", "replan"]:
    """Route after synthesis: write if briefs ready, replan if not."""
    briefs = state.get("chapter_briefs", [])
    if briefs:
        return "write"
    else:
        logger.warning("No chapter briefs generated, replanning")
        return "replan"


def should_continue_after_replan(
    state: ContentGenerationState,
) -> Literal["research", "done"]:
    """Route after replan: continue research or finish."""
    if state.get("needs_replan", False):
        return "research"
    else:
        return "done"


def build_content_generation_graph() -> StateGraph:
    """Build the main content generation workflow graph.

    The graph follows this flow:
    1. Research: Find sources
    2. Verify: Validate sources
    3. Extract: Extract claims from sources
    4. Cross-check: Verify claims across sources
    5. Synthesize: Create chapter briefs
    6. Write: Generate content
    7. Summarize: Update book memory
    8. Integrate: Check consistency
    9. Replan: Decide to continue or finish

    Returns:
        Compiled StateGraph ready for execution
    """
    graph = StateGraph(ContentGenerationState)

    graph.add_node("research", research_node)
    graph.add_node("verify", verify_node)
    graph.add_node("extract", extract_node)
    graph.add_node("cross_check", cross_check_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("write", write_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("integrate", integrate_node)
    graph.add_node("replan", replan_node)

    graph.add_edge(START, "research")

    graph.add_edge("research", "verify")

    graph.add_conditional_edges(
        "verify",
        should_continue_after_verify,
        {
            "extract": "extract",
            "replan": "replan",
        },
    )

    graph.add_edge("extract", "cross_check")

    graph.add_edge("cross_check", "synthesize")

    graph.add_conditional_edges(
        "synthesize",
        should_continue_after_synthesize,
        {
            "write": "write",
            "replan": "replan",
        },
    )

    graph.add_edge("write", "summarize")

    graph.add_edge("summarize", "integrate")

    graph.add_edge("integrate", "replan")

    graph.add_conditional_edges(
        "replan",
        should_continue_after_replan,
        {
            "research": "research",
            "done": END,
        },
    )

    return graph.compile()


_compiled_graph = None


def get_content_generation_graph() -> StateGraph:
    """Get the singleton compiled graph instance."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_content_generation_graph()
    return _compiled_graph


async def run_content_generation(
    topic: str,
    subtopics: list[str] | None = None,
    focus_areas: list[str] | None = None,
    target_word_count: int = 50000,
    depth: str = "standard",
    style_preferences: dict[str, str] | None = None,
    max_iterations: int = 5,
) -> ContentGenerationState:
    """Run the content generation workflow.

    Args:
        topic: Main topic for the content
        subtopics: List of subtopics to cover
        focus_areas: Specific areas to focus on
        target_word_count: Target length in words
        depth: Depth level (overview, standard, deep, exhaustive)
        style_preferences: Writing style preferences
        max_iterations: Maximum research-write iterations

    Returns:
        Final state with all generated content and artifacts
    """
    from prolific.agent.state import create_initial_state

    initial_state = create_initial_state(
        topic=topic,
        subtopics=subtopics,
        focus_areas=focus_areas,
        target_word_count=target_word_count,
        depth=depth,
        style_preferences=style_preferences,
        max_iterations=max_iterations,
    )

    graph = get_content_generation_graph()

    logger.info(f"Starting content generation for topic: {topic}")

    final_state = await graph.ainvoke(initial_state)

    logger.info(
        f"Content generation complete. "
        f"Words: {final_state.get('global_memory', {}).current_word_count if final_state.get('global_memory') else 0}"
    )

    return final_state


async def stream_content_generation(
    topic: str,
    subtopics: list[str] | None = None,
    focus_areas: list[str] | None = None,
    target_word_count: int = 50000,
    depth: str = "standard",
    style_preferences: dict[str, str] | None = None,
    max_iterations: int = 5,
):
    """Stream the content generation workflow with progress updates.

    Yields intermediate states for progress tracking.

    Args:
        topic: Main topic for the content
        subtopics: List of subtopics to cover
        focus_areas: Specific areas to focus on
        target_word_count: Target length in words
        depth: Depth level
        style_preferences: Writing style preferences
        max_iterations: Maximum iterations

    Yields:
        Intermediate states with phase info and progress
    """
    from prolific.agent.state import create_initial_state

    initial_state = create_initial_state(
        topic=topic,
        subtopics=subtopics,
        focus_areas=focus_areas,
        target_word_count=target_word_count,
        depth=depth,
        style_preferences=style_preferences,
        max_iterations=max_iterations,
    )

    graph = get_content_generation_graph()

    async for state in graph.astream(initial_state):
        node_name = list(state.keys())[0] if state else "unknown"
        node_state = state.get(node_name, {})

        yield {
            "node": node_name,
            "phase": node_state.get("current_phase", "unknown"),
            "iteration": node_state.get("iteration_count", 0),
            "messages": [
                m.content for m in node_state.get("messages", [])[-3:]
            ],
            "source_count": len(node_state.get("approved_sources", [])),
            "claim_count": len(node_state.get("claims", [])),
            "chapter_count": len(node_state.get("draft_chunks", [])),
            "word_count": sum(
                c.word_count for c in node_state.get("draft_chunks", [])
            ),
        }
