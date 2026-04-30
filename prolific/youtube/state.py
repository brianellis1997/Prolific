"""LangGraph state for the YouTube sleep history pipeline."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage

from prolific.agent.state import merge_artifacts_by_id, replace_value
from prolific.youtube.schemas import (
    AudioChunk,
    ImageAsset,
    ScriptSection,
    ThumbnailAsset,
    VideoMetadata,
)


class YouTubePipelineState(TypedDict):
    """State flowing through the YouTube video generation workflow."""

    thread_id: str

    # Topic
    topic: str
    era_tags: list[str]
    region_tags: list[str]
    is_biography: bool
    past_video_topics: list[str]
    selection_rationale: str
    is_intentional_continuation: bool
    continues_video_id: str | None
    # One of "BIOGRAPHY" (Mon/Wed/Fri), "LOST_CIVILIZATION" (Thu), "IMMERSIVE_DAILY_LIFE" (Sat).
    # Injected by scheduler or /api/v1/youtube/generate; defaults to BIOGRAPHY for back-compat.
    content_mode: str

    # Script
    script_sections: Annotated[list[ScriptSection], merge_artifacts_by_id]
    total_script_word_count: int

    # Images
    image_assets: Annotated[list[ImageAsset], merge_artifacts_by_id]
    thumbnail: Annotated[ThumbnailAsset | None, replace_value]

    # Audio
    audio_chunks: Annotated[list[AudioChunk], merge_artifacts_by_id]
    final_audio_path: str

    # Video
    final_video_path: str
    video_metadata: Annotated[VideoMetadata | None, replace_value]

    # Upload
    youtube_video_id: str
    youtube_url: str

    # Workflow control
    current_phase: str
    messages: Annotated[list[BaseMessage], operator.add]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]


def create_initial_youtube_state(
    thread_id: str | None = None,
    content_mode: str = "BIOGRAPHY",
) -> YouTubePipelineState:
    """Create initial state for a YouTube pipeline run.

    `content_mode` is one of BIOGRAPHY / LOST_CIVILIZATION / IMMERSIVE_DAILY_LIFE.
    The scheduler injects it per cron job; manual API triggers can override it.
    """
    from uuid import uuid4

    if thread_id is None:
        thread_id = str(uuid4())

    return YouTubePipelineState(
        thread_id=thread_id,
        topic="",
        era_tags=[],
        region_tags=[],
        is_biography=False,
        past_video_topics=[],
        selection_rationale="",
        is_intentional_continuation=False,
        continues_video_id=None,
        content_mode=content_mode,
        script_sections=[],
        total_script_word_count=0,
        image_assets=[],
        thumbnail=None,
        audio_chunks=[],
        final_audio_path="",
        final_video_path="",
        video_metadata=None,
        youtube_video_id="",
        youtube_url="",
        current_phase="topic_selection",
        messages=[],
        errors=[],
        warnings=[],
    )
