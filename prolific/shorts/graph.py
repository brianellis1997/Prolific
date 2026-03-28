"""LangGraph workflow assembly for the shorts pipeline with content mode routing."""

import logging
from typing import Literal

from langgraph.graph import END, START, StateGraph

from prolific.shorts.nodes import (
    clip_analysis_node,
    clip_sourcing_node,
    compilation_research_node,
    image_generation_node,
    metadata_generation_node,
    script_writing_node,
    stock_clip_sourcing_node,
    story_direction_node,
    story_review_node,
    streaming_discovery_node,
    topic_selection_node,
    tts_generation_node,
    video_assembly_node,
    visual_planning_node,
    youtube_upload_node,
)
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


def _route_by_content_mode(
    state: ShortsPipelineState,
) -> Literal["clip_sourcing", "compilation_research", "script_writing", "twitch_discovery"]:
    """Route to the correct sub-pipeline based on content_mode."""
    mode = state.get("content_mode", "news_commentary")
    if mode == "twitch_clips":
        return "twitch_discovery"
    elif mode == "clip_compilation":
        return "compilation_research"
    elif mode in ("clip_reaction", "niche_drama"):
        return "clip_sourcing"
    else:
        return "script_writing"


def _route_after_clip_analysis(
    state: ShortsPipelineState,
) -> str:
    """After clip analysis: use Director Agent if we have source clips, else fall back to script."""
    source_clips = state.get("source_clips", [])
    if source_clips:
        return "story_direction"
    return "script_writing"


def _route_after_story_review(
    state: ShortsPipelineState,
) -> str:
    """After review: approve (continue to assets) or retry (back to story_direction)."""
    story_plan = state.get("story_plan")
    if story_plan is None:
        return "story_direction"
    return "asset_generation"


def _route_after_visual_planning(
    state: ShortsPipelineState,
) -> list[str]:
    """Determine which asset generation nodes to fan out to."""
    visual_assets = state.get("visual_assets", [])
    has_stock = any(a.asset_type == "stock_clip" and not a.file_path for a in visual_assets)
    has_web = any(a.asset_type in ("ai_image", "web_image") and not a.file_path for a in visual_assets)

    targets = []
    if has_stock:
        targets.append("stock_clip_sourcing")
    if has_web:
        targets.append("image_generation")
    if not targets:
        targets.append("tts_generation")
    return targets


def build_shorts_pipeline_graph(checkpointer=None):
    """Build the shorts video generation workflow with content mode routing.

    Pipeline routes:
      news_commentary:  topic -> script -> visual_plan -> [stock, images] -> tts -> assembly -> meta -> upload
      clip_reaction:    topic -> clip_sourcing -> clip_analysis -> story_direction -> [stock, images] -> tts -> assembly -> upload
      clip_compilation: topic -> compilation_research -> clip_sourcing -> clip_analysis -> story_direction -> ... -> upload
      niche_drama:      topic -> clip_sourcing -> clip_analysis -> story_direction -> [stock, images] -> tts -> assembly -> upload
      twitch_clips:     topic -> twitch_discovery -> clip_sourcing -> clip_analysis -> story_direction -> ... -> upload

    story_direction replaces script_writing + visual_planning for all clip-based modes.
    It produces a StoryPlan with clip_plays/narrate/narrate_over segments and derives
    ShortScript + VisualAsset list for downstream compatibility.
    """
    graph = StateGraph(ShortsPipelineState)

    graph.add_node("topic_selection", topic_selection_node)
    graph.add_node("twitch_discovery", streaming_discovery_node)
    graph.add_node("compilation_research", compilation_research_node)
    graph.add_node("clip_sourcing", clip_sourcing_node)
    graph.add_node("clip_analysis", clip_analysis_node)
    graph.add_node("story_direction", story_direction_node)
    graph.add_node("story_review", story_review_node)
    graph.add_node("script_writing", script_writing_node)
    graph.add_node("visual_planning", visual_planning_node)
    graph.add_node("stock_clip_sourcing", stock_clip_sourcing_node)
    graph.add_node("image_generation", image_generation_node)
    graph.add_node("tts_generation", tts_generation_node)
    graph.add_node("video_assembly", video_assembly_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("youtube_upload", youtube_upload_node)

    graph.add_edge(START, "topic_selection")

    graph.add_conditional_edges(
        "topic_selection",
        _route_by_content_mode,
        {
            "twitch_discovery": "twitch_discovery",
            "compilation_research": "compilation_research",
            "clip_sourcing": "clip_sourcing",
            "script_writing": "script_writing",
        },
    )

    graph.add_edge("twitch_discovery", "clip_sourcing")
    graph.add_edge("compilation_research", "clip_sourcing")
    graph.add_edge("clip_sourcing", "clip_analysis")

    graph.add_conditional_edges(
        "clip_analysis",
        _route_after_clip_analysis,
        {"story_direction": "story_direction", "script_writing": "script_writing"},
    )

    graph.add_edge("story_direction", "story_review")

    graph.add_conditional_edges(
        "story_review",
        _route_after_story_review,
        {
            "story_direction": "story_direction",
            "asset_generation": "image_generation",
        },
    )

    graph.add_edge("script_writing", "visual_planning")

    graph.add_conditional_edges(
        "visual_planning",
        _route_after_visual_planning,
        {
            "stock_clip_sourcing": "stock_clip_sourcing",
            "image_generation": "image_generation",
            "tts_generation": "tts_generation",
        },
    )

    graph.add_edge("stock_clip_sourcing", "tts_generation")
    graph.add_edge("image_generation", "tts_generation")
    graph.add_edge("tts_generation", "video_assembly")
    graph.add_edge("video_assembly", "metadata_generation")
    graph.add_edge("metadata_generation", "youtube_upload")
    graph.add_edge("youtube_upload", END)

    return graph.compile(checkpointer=checkpointer)


def _shorts_run_config(thread_id: str, niche: str | None = None) -> dict:
    """Build LangGraph run config with LangSmith metadata for Shorts runs."""
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": f"shorts-{niche or 'general'}-{thread_id[:8]}",
        "tags": ["shorts", niche or "general"],
        "metadata": {
            "pipeline": "shorts",
            "niche": niche or "general",
            "thread_id": thread_id,
        },
    }


async def run_shorts_pipeline(
    thread_id: str | None = None,
    niche: str | None = None,
) -> dict:
    """Run the full shorts pipeline and return final state."""
    import os
    os.environ.setdefault("LANGCHAIN_PROJECT", "prolific-shorts")

    from prolific.core.pipeline_lock import acquire_pipeline, release_pipeline
    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
    if niche:
        initial_state["niche"] = niche

    run_id = acquire_pipeline("wait_really_shorts", topic=initial_state.get("topic", ""))
    try:
        graph = build_shorts_pipeline_graph()
        config = _shorts_run_config(initial_state["thread_id"], niche)
        final_state = await graph.ainvoke(initial_state, config=config)
        return final_state
    finally:
        release_pipeline(run_id)


async def stream_shorts_pipeline(
    thread_id: str | None = None,
    niche: str | None = None,
):
    """Stream the shorts pipeline with progress updates."""
    import os
    os.environ.setdefault("LANGCHAIN_PROJECT", "prolific-shorts")

    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
    if niche:
        initial_state["niche"] = niche

    graph = build_shorts_pipeline_graph()
    config = _shorts_run_config(initial_state["thread_id"], niche)

    yield {
        "thread_id": initial_state["thread_id"],
        "node": "init",
        "phase": "starting",
        "messages": ["Starting shorts pipeline"],
    }

    accumulated_state = dict(initial_state)

    async for state in graph.astream(initial_state, config=config):
        node_name = list(state.keys())[0] if state else "unknown"
        node_state = state.get(node_name, {})

        for key, value in node_state.items():
            if value is not None:
                accumulated_state[key] = value

        messages = node_state.get("messages", [])
        message_contents = []
        for m in messages[-3:]:
            if hasattr(m, "content"):
                message_contents.append(m.content)

        yield {
            "thread_id": accumulated_state["thread_id"],
            "node": node_name,
            "phase": node_state.get("current_phase", node_name),
            "topic": accumulated_state.get("topic", ""),
            "content_mode": accumulated_state.get("content_mode", "news_commentary"),
            "messages": message_contents,
            "visual_count": len(accumulated_state.get("visual_assets", [])),
            "source_clip_count": len(accumulated_state.get("source_clips", [])),
        }

    yield {"_final_state": accumulated_state}
