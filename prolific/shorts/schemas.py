"""Pydantic models for the shorts pipeline artifacts."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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


class VisualAsset(BaseModel):
    """A visual segment (stock clip or AI image) for the short."""

    id: UUID = Field(default_factory=uuid4)
    sequence_number: int
    asset_type: Literal["stock_clip", "ai_image"] = "ai_image"
    search_query: str = ""
    image_prompt: str = ""
    file_path: str | None = None
    width: int = 1080
    height: int = 1920
    duration_seconds: float = 2.5
    ken_burns_direction: str = "zoom_in"

    class Config:
        frozen = False


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
