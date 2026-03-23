"""Pydantic models for the shorts pipeline artifacts."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SegmentDirective(BaseModel):
    """A single story segment directive from the Director Agent."""

    sequence_number: int
    mode: Literal["narrate", "clip_plays", "narrate_over"] = "narrate"
    narration_text: str = ""
    source_clip_index: int | None = None
    clip_start_seconds: float = 0.0
    clip_duration_seconds: float | None = None
    asset_type: str = "web_image"
    search_query: str = ""
    ken_burns_direction: str = "zoom_in"
    why: str = ""


class StoryPlan(BaseModel):
    """Director Agent output: ordered story segments with audio/visual decisions."""

    segments: list[SegmentDirective] = Field(default_factory=list)
    hook: str = ""


class ShortScript(BaseModel):
    """Script for a short-form video (25-30 seconds)."""

    id: UUID = Field(default_factory=uuid4)
    hook: str = ""
    setup: str = ""
    value_body: str = ""
    cta_loop: str = ""
    full_text: str = ""
    word_count: int = 0
    visual_suggestions: list[str] = Field(default_factory=list)

    class Config:
        frozen = False


class SourceClip(BaseModel):
    """A clip downloaded from YouTube/Twitch/Reddit for reuse."""

    id: UUID = Field(default_factory=uuid4)
    platform: Literal["twitch", "kick", "youtube", "reddit", "other"] = "other"
    original_url: str = ""
    creator_name: str = ""
    clip_title: str = ""
    file_path: str | None = None
    audio_path: str = ""
    duration_seconds: float = 0.0
    transcript: str = ""
    sequence_number: int = 0
    view_count: int = 0

    class Config:
        frozen = False


class VisualAsset(BaseModel):
    """A visual segment (stock clip, web image, or source clip) for the short."""

    id: UUID = Field(default_factory=uuid4)
    sequence_number: int
    asset_type: Literal["stock_clip", "ai_image", "web_image", "source_clip"] = "ai_image"
    search_query: str = ""
    image_prompt: str = ""
    file_path: str | None = None
    width: int = 1080
    height: int = 1920
    duration_seconds: float = 2.5
    ken_burns_direction: str = "zoom_in"
    script_text: str = ""

    class Config:
        frozen = False


class ClipVisualAnalysis(BaseModel):
    """Vision model analysis of video clip frames."""

    people_visible: list[str] = Field(default_factory=list)
    actions_described: list[str] = Field(default_factory=list)
    setting: str = ""
    on_screen_text: list[str] = Field(default_factory=list)
    emotional_tone: str = ""
    visual_summary: str = ""


class TimestampedMoment(BaseModel):
    """A key moment in a clip with its approximate timestamp."""
    description: str = ""
    timestamp_seconds: float = 0.0


class ClipContentUnderstanding(BaseModel):
    """Combined transcript + visual understanding of a clip."""

    transcript: str = ""
    visual_analysis: ClipVisualAnalysis | None = None
    clip_duration_seconds: float = 0.0
    content_summary: str = ""
    key_moments: list[str] = Field(default_factory=list)
    timestamped_moments: list[TimestampedMoment] = Field(default_factory=list)


class CaptionSegment(BaseModel):
    """A word-level caption with timing."""

    word: str
    start_time: float
    end_time: float


class ShortsVideoMetadata(BaseModel):
    """YouTube Shorts upload metadata."""

    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category_id: str = "22"
    privacy_status: str = "unlisted"

    class Config:
        frozen = False


class ShortRecord(BaseModel):
    """Record of a published (or in-progress) short."""

    id: UUID = Field(default_factory=uuid4)
    topic: str
    hook: str = ""
    script_text: str = ""
    word_count: int = 0
    duration_seconds: float = 0.0
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    video_path: str | None = None
    status: str = "planned"
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None

    class Config:
        frozen = False
