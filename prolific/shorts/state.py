"""LangGraph state for the shorts pipeline."""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage

from prolific.agent.state import merge_artifacts_by_id, replace_value
from prolific.core.config import settings
from prolific.shorts.schemas import (
    CaptionSegment,
    ClipContentUnderstanding,
    ShortScript,
    ShortsVideoMetadata,
    SourceClip,
    StoryPlan,
    VisualAsset,
)


class ShortsPipelineState(TypedDict):
    """State flowing through the shorts video generation workflow."""

    thread_id: str

    topic: str
    topic_type: str
    content_mode: str
    niche: str
    source_urls: list[str]
    past_short_topics: list[str]
    compilation_items: list[str]
    scene_ideas: list[str]
    selected_character: str
    attribution_texts: Annotated[list[str], operator.add]

    clip_content_understanding: Annotated[list[ClipContentUnderstanding] | None, replace_value]

    story_plan: Annotated[StoryPlan | None, replace_value]
    story_direction_attempts: int
    story_review_feedback: str

    script: Annotated[ShortScript | None, replace_value]

    source_clips: Annotated[list[SourceClip], merge_artifacts_by_id]
    visual_assets: Annotated[list[VisualAsset], merge_artifacts_by_id]

    audio_path: str
    audio_duration_seconds: float
    audio_segment_paths: list[str]

    caption_segments: Annotated[list[CaptionSegment] | None, replace_value]
    subtitle_path: str

    final_video_path: str
    video_metadata: Annotated[ShortsVideoMetadata | None, replace_value]
    thumbnail_path: str

    youtube_video_id: str
    youtube_url: str

    current_phase: Annotated[str, replace_value]
    messages: Annotated[list[BaseMessage], operator.add]
    errors: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]


def create_initial_shorts_state(thread_id: str | None = None, niche: str | None = None) -> ShortsPipelineState:
    """Create initial state for a shorts pipeline run."""
    from uuid import uuid4

    if thread_id is None:
        thread_id = str(uuid4())

    return ShortsPipelineState(
        thread_id=thread_id,
        topic="",
        topic_type="",
        content_mode="news_commentary",
        niche=niche or settings.shorts_niche or "general",
        source_urls=[],
        past_short_topics=[],
        compilation_items=[],
        scene_ideas=[],
        selected_character="",
        attribution_texts=[],
        clip_content_understanding=None,
        story_plan=None,
        story_direction_attempts=0,
        story_review_feedback="",
        script=None,
        source_clips=[],
        visual_assets=[],
        audio_path="",
        audio_duration_seconds=0.0,
        audio_segment_paths=[],
        caption_segments=None,
        subtitle_path="",
        final_video_path="",
        video_metadata=None,
        thumbnail_path="",
        youtube_video_id="",
        youtube_url="",
        current_phase="topic_selection",
        messages=[],
        errors=[],
        warnings=[],
    )
