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
) -> Literal["clip_sourcing", "compilation_research", "script_writing"]:
    """Route to the correct sub-pipeline based on content_mode."""
    mode = state.get("content_mode", "news_commentary")
    if mode == "clip_compilation":
        return "compilation_research"
    elif mode in ("clip_reaction", "niche_drama"):
        return "clip_sourcing"
    else:
        return "script_writing"


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
      clip_reaction:    topic -> clip_sourcing -> script -> tts -> assembly -> meta -> upload
      clip_compilation: topic -> compilation_research -> clip_sourcing -> script -> tts -> assembly -> meta -> upload
      niche_drama:      topic -> clip_sourcing -> script -> visual_plan -> [stock, images] -> tts -> assembly -> meta -> upload
    """
    graph = StateGraph(ShortsPipelineState)

    graph.add_node("topic_selection", topic_selection_node)
    graph.add_node("compilation_research", compilation_research_node)
    graph.add_node("clip_sourcing", clip_sourcing_node)
    graph.add_node("clip_analysis", clip_analysis_node)
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
            "compilation_research": "compilation_research",
            "clip_sourcing": "clip_sourcing",
            "script_writing": "script_writing",
        },
    )

    graph.add_edge("compilation_research", "clip_sourcing")
    graph.add_edge("clip_sourcing", "clip_analysis")
    graph.add_edge("clip_analysis", "script_writing")
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


async def run_shorts_pipeline(
    thread_id: str | None = None,
    niche: str | None = None,
) -> dict:
    """Run the full shorts pipeline and return final state."""
    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
    if niche:
        initial_state["niche"] = niche

    graph = build_shorts_pipeline_graph()

    config = {"configurable": {"thread_id": initial_state["thread_id"]}}
    final_state = await graph.ainvoke(initial_state, config=config)

    return final_state


async def stream_shorts_pipeline(
    thread_id: str | None = None,
    niche: str | None = None,
):
    """Stream the shorts pipeline with progress updates."""
    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
    if niche:
        initial_state["niche"] = niche

    graph = build_shorts_pipeline_graph()

    config = {"configurable": {"thread_id": initial_state["thread_id"]}}

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
