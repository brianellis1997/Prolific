"""Pydantic models for the YouTube pipeline artifacts."""

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class VideoRecord(BaseModel):
    """Record of a published (or in-progress) YouTube video."""

    id: UUID = Field(default_factory=uuid4)
    topic: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    thumbnail_path: str | None = None
    video_path: str | None = None
    script_word_count: int = 0
    estimated_duration_minutes: float = 0.0
    status: str = "planned"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None
    era_tags: list[str] = Field(default_factory=list)
    region_tags: list[str] = Field(default_factory=list)
    is_biography: bool = False

    class Config:
        frozen = False


class ScriptSection(BaseModel):
    """One section of the narration script."""

    id: UUID = Field(default_factory=uuid4)
    section_number: int
    title: str
    key_points: list[str] = Field(default_factory=list)
    content: str = ""
    word_count: int = 0
    estimated_duration_minutes: float = 0.0
    image_prompt: str = ""
    audio_path: str | None = None

    class Config:
        frozen = False


class ImageAsset(BaseModel):
    """A generated image for the video."""

    id: UUID = Field(default_factory=uuid4)
    section_number: int
    prompt: str
    file_path: str | None = None
    style: str = "oil painting, historical illustration, warm muted tones, cinematic lighting"
    width: int = 1920
    height: int = 1080
    duration_seconds: float = 420.0
    ken_burns_direction: str = "zoom_in"

    class Config:
        frozen = False


class ThumbnailAsset(BaseModel):
    """The YouTube thumbnail image."""

    id: UUID = Field(default_factory=uuid4)
    prompt: str = ""
    file_path: str | None = None
    title_overlay_text: str = ""

    class Config:
        frozen = False


class AudioChunk(BaseModel):
    """A synthesized audio segment."""

    id: UUID = Field(default_factory=uuid4)
    section_number: int
    text: str = ""
    audio_path: str | None = None
    duration_seconds: float = 0.0

    class Config:
        frozen = False


class VideoMetadata(BaseModel):
    """YouTube upload metadata."""

    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    category_id: str = "27"
    privacy_status: str = "unlisted"

    class Config:
        frozen = False
