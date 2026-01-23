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
from prolific.services.checkpointer import get_checkpointer_service

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


def build_content_generation_graph(checkpointer=None) -> StateGraph:
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

    Args:
        checkpointer: Optional checkpointer for persistence

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

    return graph.compile(checkpointer=checkpointer)


async def get_content_generation_graph_with_checkpointer():
    """Get compiled graph with checkpointer for persistence."""
    checkpointer_service = get_checkpointer_service()
    saver = await checkpointer_service.get_saver()
    return build_content_generation_graph(checkpointer=saver)


def get_content_generation_graph() -> StateGraph:
    """Get compiled graph without checkpointer (for backward compatibility)."""
    return build_content_generation_graph(checkpointer=None)


async def run_content_generation(
    topic: str,
    subtopics: list[str] | None = None,
    focus_areas: list[str] | None = None,
    target_word_count: int = 50000,
    depth: str = "standard",
    style_preferences: dict[str, str] | None = None,
    max_iterations: int = 5,
    thread_id: str | None = None,
) -> tuple[ContentGenerationState, str]:
    """Run the content generation workflow with persistence.

    Args:
        topic: Main topic for the content
        subtopics: List of subtopics to cover
        focus_areas: Specific areas to focus on
        target_word_count: Target length in words
        depth: Depth level (overview, standard, deep, exhaustive)
        style_preferences: Writing style preferences
        max_iterations: Maximum research-write iterations
        thread_id: Optional thread ID to resume from. If None, starts new generation.

    Returns:
        Tuple of (final state, thread_id) for recovery
    """
    from prolific.agent.state import create_initial_state

    checkpointer_service = get_checkpointer_service()

    if thread_id is None:
        thread_id = checkpointer_service.generate_thread_id()
        initial_state = create_initial_state(
            topic=topic,
            subtopics=subtopics,
            focus_areas=focus_areas,
            target_word_count=target_word_count,
            depth=depth,
            style_preferences=style_preferences,
            max_iterations=max_iterations,
            thread_id=thread_id,
        )
        logger.info(f"Starting new content generation for topic: {topic}, thread_id: {thread_id}")
    else:
        existing_state = await checkpointer_service.get_thread_state(thread_id)
        if existing_state:
            initial_state = existing_state
            logger.info(f"Resuming content generation from thread_id: {thread_id}")
        else:
            initial_state = create_initial_state(
                topic=topic,
                subtopics=subtopics,
                focus_areas=focus_areas,
                target_word_count=target_word_count,
                depth=depth,
                style_preferences=style_preferences,
                max_iterations=max_iterations,
                thread_id=thread_id,
            )
            logger.info(f"Thread not found, starting new generation with thread_id: {thread_id}")

    graph = await get_content_generation_graph_with_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    final_state = await graph.ainvoke(initial_state, config=config)

    logger.info(
        f"Content generation complete. thread_id: {thread_id}, "
        f"Words: {final_state.get('global_memory', {}).current_word_count if final_state.get('global_memory') else 0}"
    )

    return final_state, thread_id


async def stream_content_generation(
    topic: str,
    subtopics: list[str] | None = None,
    focus_areas: list[str] | None = None,
    target_word_count: int = 50000,
    depth: str = "standard",
    style_preferences: dict[str, str] | None = None,
    max_iterations: int = 5,
    thread_id: str | None = None,
):
    """Stream the content generation workflow with progress updates and persistence.

    Yields intermediate states for progress tracking, and final state at end.
    Uses checkpointing for persistence so generation can be resumed if interrupted.

    Args:
        topic: Main topic for the content
        subtopics: List of subtopics to cover
        focus_areas: Specific areas to focus on
        target_word_count: Target length in words
        depth: Depth level
        style_preferences: Writing style preferences
        max_iterations: Maximum iterations
        thread_id: Optional thread ID to resume from. If None, starts new generation.

    Yields:
        Intermediate states with phase info and progress.
        Final yield includes _final_state with complete state and thread_id.
    """
    from prolific.agent.state import create_initial_state

    checkpointer_service = get_checkpointer_service()

    if thread_id is None:
        thread_id = checkpointer_service.generate_thread_id()
        initial_state = create_initial_state(
            topic=topic,
            subtopics=subtopics,
            focus_areas=focus_areas,
            target_word_count=target_word_count,
            depth=depth,
            style_preferences=style_preferences,
            max_iterations=max_iterations,
            thread_id=thread_id,
        )
        logger.info(f"Starting new streamed generation for topic: {topic}, thread_id: {thread_id}")
    else:
        existing_state = await checkpointer_service.get_thread_state(thread_id)
        if existing_state:
            initial_state = existing_state
            logger.info(f"Resuming streamed generation from thread_id: {thread_id}")
        else:
            initial_state = create_initial_state(
                topic=topic,
                subtopics=subtopics,
                focus_areas=focus_areas,
                target_word_count=target_word_count,
                depth=depth,
                style_preferences=style_preferences,
                max_iterations=max_iterations,
                thread_id=thread_id,
            )
            logger.info(f"Thread not found, starting new streamed generation with thread_id: {thread_id}")

    graph = await get_content_generation_graph_with_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    from prolific.agent.state import merge_artifacts_by_id, merge_dicts

    LIST_MERGE_FIELDS = {
        "claims", "approved_sources", "evidence_snippets", "source_candidates",
        "chapter_briefs", "draft_chunks", "content_gaps"
    }
    APPEND_FIELDS = {"messages", "errors", "warnings"}
    DICT_MERGE_FIELDS = {"local_memories"}

    accumulated_state = dict(initial_state)

    yield {
        "thread_id": thread_id,
        "node": "init",
        "phase": "starting",
        "iteration": 0,
        "messages": [f"Starting generation with thread_id: {thread_id}"],
        "source_count": 0,
        "claim_count": 0,
        "chapter_count": 0,
        "word_count": 0,
    }

    async for state in graph.astream(initial_state, config=config):
        node_name = list(state.keys())[0] if state else "unknown"
        node_state = state.get(node_name, {})

        for key, value in node_state.items():
            if value is not None:
                if key in LIST_MERGE_FIELDS:
                    accumulated_state[key] = merge_artifacts_by_id(
                        accumulated_state.get(key, []), value
                    )
                elif key in APPEND_FIELDS:
                    accumulated_state[key] = accumulated_state.get(key, []) + value
                elif key in DICT_MERGE_FIELDS:
                    accumulated_state[key] = merge_dicts(
                        accumulated_state.get(key, {}), value
                    )
                else:
                    accumulated_state[key] = value

        messages = node_state.get("messages", [])
        message_contents = []
        for m in messages[-3:]:
            if hasattr(m, "content"):
                message_contents.append(m.content)
            elif isinstance(m, str):
                message_contents.append(m)

        yield {
            "thread_id": thread_id,
            "node": node_name,
            "phase": node_state.get("current_phase", node_name),
            "iteration": node_state.get("iteration_count", 0),
            "messages": message_contents,
            "source_count": len(accumulated_state.get("approved_sources", [])),
            "claim_count": len(accumulated_state.get("claims", [])),
            "chapter_count": len(accumulated_state.get("draft_chunks", [])),
            "word_count": sum(
                c.word_count for c in accumulated_state.get("draft_chunks", [])
            ),
        }

    yield {"_final_state": accumulated_state, "thread_id": thread_id}
