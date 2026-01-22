"""Memory structures for maintaining coherence across long documents.

Two-track memory system:
- GlobalBookMemory: Persistent state across the entire book
- LocalChapterMemory: Working memory for a specific chapter
"""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class GlossaryEntry(BaseModel):
    """Term definition for consistency across the manuscript."""

    term: str
    definition: str
    first_introduced_chapter: int
    aliases: list[str] = Field(default_factory=list)
    usage_count: int = 1

    class Config:
        frozen = False


class StyleGuide(BaseModel):
    """Writing style parameters enforced across all chapters."""

    tone: Literal["academic", "conversational", "technical", "journalistic"] = (
        "academic"
    )
    person: Literal["first", "second", "third"] = "third"
    formality_level: float = Field(ge=0.0, le=1.0, default=0.7)  # 0=casual, 1=formal
    sentence_length_target: Literal["short", "medium", "long", "varied"] = "varied"
    use_contractions: bool = False
    citation_style: Literal["inline", "footnote", "endnote", "hyperlink"] = "inline"
    custom_rules: list[str] = Field(default_factory=list)

    class Config:
        frozen = False


class GlobalBookMemory(BaseModel):
    """Persistent state across the entire book generation.

    This is the "global memory" track that maintains coherence
    and prevents repetition across all chapters.
    """

    # Project metadata
    project_id: UUID = Field(default_factory=uuid4)
    title: str = ""
    subtitle: str | None = None
    target_word_count: int = 50000
    current_word_count: int = 0
    depth_level: Literal["overview", "standard", "deep", "exhaustive"] = "standard"

    # Structure
    outline_ids: list[UUID] = Field(default_factory=list)
    chapter_order: list[UUID] = Field(default_factory=list)

    # Style
    style_guide: StyleGuide = Field(default_factory=StyleGuide)
    glossary: dict[str, GlossaryEntry] = Field(default_factory=dict)

    # Knowledge base references
    claim_ledger_ids: set[UUID] = Field(default_factory=set)
    approved_source_ids: set[UUID] = Field(default_factory=set)

    # Progress tracking
    completed_chapters: list[UUID] = Field(default_factory=list)
    rolling_summary: str = ""  # Updated after each chapter
    topics_covered: set[str] = Field(default_factory=set)
    topics_remaining: set[str] = Field(default_factory=set)

    # Anti-repetition tracking
    key_phrases_used: dict[str, int] = Field(default_factory=dict)  # phrase -> count
    metaphors_used: list[str] = Field(default_factory=list)
    examples_used: list[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False


class LocalChapterMemory(BaseModel):
    """Working memory for a specific chapter being written.

    This is the "local memory" track with only what's relevant
    for the current chapter, keeping context size manageable.
    """

    chapter_id: UUID
    chapter_number: int

    # Working set (subset of global data)
    relevant_claims: list[UUID] = Field(default_factory=list)
    relevant_sources: list[UUID] = Field(default_factory=list)
    evidence_snippets: list[UUID] = Field(default_factory=list)

    # Draft state
    current_drafts: list[UUID] = Field(default_factory=list)
    revision_count: int = 0

    # Context from neighbors
    preceding_chapter_summary: str = ""
    following_chapter_preview: str = ""

    # Local tracking
    terms_introduced: list[str] = Field(default_factory=list)
    claims_used: set[UUID] = Field(default_factory=set)
    word_count: int = 0

    class Config:
        frozen = False
