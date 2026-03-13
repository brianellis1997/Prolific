"""LangGraph workflow assembly for the shorts pipeline."""

import logging

from langgraph.graph import END, START, StateGraph

from prolific.shorts.nodes import (
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


def build_shorts_pipeline_graph(checkpointer=None):
    """Build the shorts video generation workflow.

    Pipeline: topic_selection -> script_writing -> visual_planning
        -> [stock_clip_sourcing, image_generation] (parallel)
        -> tts_generation -> video_assembly -> metadata_generation
        -> youtube_upload
    """
    graph = StateGraph(ShortsPipelineState)

    graph.add_node("topic_selection", topic_selection_node)
    graph.add_node("script_writing", script_writing_node)
    graph.add_node("visual_planning", visual_planning_node)
    graph.add_node("stock_clip_sourcing", stock_clip_sourcing_node)
    graph.add_node("image_generation", image_generation_node)
    graph.add_node("tts_generation", tts_generation_node)
    graph.add_node("video_assembly", video_assembly_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("youtube_upload", youtube_upload_node)

    graph.add_edge(START, "topic_selection")
    graph.add_edge("topic_selection", "script_writing")
    graph.add_edge("script_writing", "visual_planning")
    graph.add_edge("visual_planning", "stock_clip_sourcing")
    graph.add_edge("visual_planning", "image_generation")
    graph.add_edge("stock_clip_sourcing", "tts_generation")
    graph.add_edge("image_generation", "tts_generation")
    graph.add_edge("tts_generation", "video_assembly")
    graph.add_edge("video_assembly", "metadata_generation")
    graph.add_edge("metadata_generation", "youtube_upload")
    graph.add_edge("youtube_upload", END)

    return graph.compile(checkpointer=checkpointer)


async def run_shorts_pipeline(thread_id: str | None = None) -> dict:
    """Run the full shorts pipeline and return final state."""
    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
    graph = build_shorts_pipeline_graph()

    config = {"configurable": {"thread_id": initial_state["thread_id"]}}
    final_state = await graph.ainvoke(initial_state, config=config)

    return final_state


async def stream_shorts_pipeline(thread_id: str | None = None):
    """Stream the shorts pipeline with progress updates."""
    from prolific.shorts.state import create_initial_shorts_state

    initial_state = create_initial_shorts_state(thread_id=thread_id)
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
            "messages": message_contents,
            "visual_count": len(accumulated_state.get("visual_assets", [])),
        }

    yield {"_final_state": accumulated_state}
