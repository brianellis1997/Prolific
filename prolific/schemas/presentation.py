"""Pydantic models for presentation generation.

Defines the structured output schema that the LLM returns when
planning a PowerPoint presentation from article content.
"""

from enum import Enum

from pydantic import BaseModel, Field


class SlideType(str, Enum):
    TITLE = "title"
    SECTION_DIVIDER = "section_divider"
    KEY_POINTS = "key_points"
    IMAGE_FEATURE = "image_feature"
    QUOTE_HIGHLIGHT = "quote_highlight"
    COMPARISON = "comparison"
    SOURCES = "sources"
    CLOSING = "closing"


class SlideContent(BaseModel):
    slide_type: SlideType
    title: str = ""
    subtitle: str | None = None
    bullet_points: list[str] = Field(default_factory=list)
    quote_text: str | None = None
    quote_attribution: str | None = None
    image_index: int | None = None
    image_caption: str | None = None
    section_number: int | None = None
    speaker_notes: str


class PresentationPlan(BaseModel):
    presentation_title: str
    presentation_subtitle: str
    total_slides: int = Field(ge=5, le=40)
    slides: list[SlideContent]
    key_takeaway: str
