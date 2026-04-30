"""LangGraph workflow assembly for the YouTube sleep history pipeline."""

import logging

from langgraph.graph import END, START, StateGraph

from prolific.youtube.nodes import (
    image_generation_node,
    image_planning_node,
    metadata_generation_node,
    script_planning_node,
    script_writing_node,
    thumbnail_generation_node,
    topic_selection_node,
    tts_generation_node,
    video_assembly_node,
    youtube_upload_node,
)
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


def build_youtube_pipeline_graph(checkpointer=None):
    """Build the YouTube video generation workflow.

    Pipeline: topic_selection -> script_planning -> script_writing
        -> image_planning -> image_generation -> thumbnail_generation
        -> tts_generation -> video_assembly -> metadata_generation
        -> youtube_upload
    """
    graph = StateGraph(YouTubePipelineState)

    graph.add_node("topic_selection", topic_selection_node)
    graph.add_node("script_planning", script_planning_node)
    graph.add_node("script_writing", script_writing_node)
    graph.add_node("image_planning", image_planning_node)
    graph.add_node("image_generation", image_generation_node)
    graph.add_node("thumbnail_generation", thumbnail_generation_node)
    graph.add_node("tts_generation", tts_generation_node)
    graph.add_node("video_assembly", video_assembly_node)
    graph.add_node("metadata_generation", metadata_generation_node)
    graph.add_node("youtube_upload", youtube_upload_node)

    graph.add_edge(START, "topic_selection")
    graph.add_edge("topic_selection", "script_planning")
    graph.add_edge("script_planning", "script_writing")
    graph.add_edge("script_writing", "image_planning")
    graph.add_edge("image_planning", "image_generation")
    graph.add_edge("image_generation", "thumbnail_generation")
    graph.add_edge("thumbnail_generation", "tts_generation")
    graph.add_edge("tts_generation", "video_assembly")
    graph.add_edge("video_assembly", "metadata_generation")
    graph.add_edge("metadata_generation", "youtube_upload")
    graph.add_edge("youtube_upload", END)

    return graph.compile(checkpointer=checkpointer)


async def run_youtube_pipeline(
    thread_id: str | None = None,
    content_mode: str = "BIOGRAPHY",
) -> dict:
    """Run the full YouTube pipeline and return final state.

    `content_mode` is one of BIOGRAPHY (Mon/Wed/Fri), LOST_CIVILIZATION (Thu),
    IMMERSIVE_DAILY_LIFE (Sat). Defaults to BIOGRAPHY for back-compat.
    """
    from prolific.core.pipeline_lock import acquire_pipeline, release_pipeline
    from prolific.youtube.state import create_initial_youtube_state

    initial_state = create_initial_youtube_state(thread_id=thread_id, content_mode=content_mode)

    run_id = acquire_pipeline("slumber_archives_youtube")
    try:
        graph = build_youtube_pipeline_graph()
        config = {"configurable": {"thread_id": initial_state["thread_id"]}}
        final_state = await graph.ainvoke(initial_state, config=config)
        return final_state
    finally:
        release_pipeline(run_id)


async def stream_youtube_pipeline(
    thread_id: str | None = None,
    content_mode: str = "BIOGRAPHY",
):
    """Stream the YouTube pipeline with progress updates."""
    from prolific.youtube.state import create_initial_youtube_state

    initial_state = create_initial_youtube_state(thread_id=thread_id, content_mode=content_mode)
    graph = build_youtube_pipeline_graph()

    config = {"configurable": {"thread_id": initial_state["thread_id"]}}

    yield {
        "thread_id": initial_state["thread_id"],
        "node": "init",
        "phase": "starting",
        "messages": ["Starting YouTube pipeline"],
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
            "section_count": len(accumulated_state.get("script_sections", [])),
            "word_count": accumulated_state.get("total_script_word_count", 0),
            "image_count": sum(
                1 for a in accumulated_state.get("image_assets", []) if a.file_path
            ),
            "audio_chunks": len(accumulated_state.get("audio_chunks", [])),
        }

    yield {"_final_state": accumulated_state}
