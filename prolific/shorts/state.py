"""LangGraph state for the shorts pipeline."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage

from prolific.agent.state import merge_artifacts_by_id, replace_value
from prolific.shorts.schemas import (
    CaptionSegment,
    ShortScript,
    ShortsVideoMetadata,
    VisualAsset,
)


class ShortsPipelineState(TypedDict):
    """State flowing through the shorts video generation workflow."""

    thread_id: str

    topic: str
    topic_type: str
    source_urls: list[str]
    past_short_topics: list[str]

    script: Annotated[ShortScript | None, replace_value]

    visual_assets: Annotated[list[VisualAsset], merge_artifacts_by_id]

    audio_path: str
    audio_duration_seconds: float

    caption_segments: Annotated[list[CaptionSegment] | None, replace_value]
    subtitle_path: str

    final_video_path: str
    video_metadata: Annotated[ShortsVideoMetadata | None, replace_value]

    youtube_video_id: str
    youtube_url: str

    current_phase: Annotated[str, replace_value]
    messages: Annotated[list[BaseMessage], operator.add]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]


def create_initial_shorts_state(thread_id: str | None = None) -> ShortsPipelineState:
    """Create initial state for a shorts pipeline run."""
    from uuid import uuid4

    if thread_id is None:
        thread_id = str(uuid4())

    return ShortsPipelineState(
        thread_id=thread_id,
        topic="",
        topic_type="",
        source_urls=[],
        past_short_topics=[],
        script=None,
        visual_assets=[],
        audio_path="",
        audio_duration_seconds=0.0,
        caption_segments=None,
        subtitle_path="",
        final_video_path="",
        video_metadata=None,
        youtube_video_id="",
        youtube_url="",
        current_phase="topic_selection",
        messages=[],
        errors=[],
        warnings=[],
    )
