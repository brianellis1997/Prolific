"""Pydantic models for all workflow artifacts.

Every step in the content generation pipeline produces typed artifacts.
This ensures "artifacts over chat" - structured data instead of loose messages.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ConfidenceLevel(str, Enum):
    """Confidence level for claims based on source corroboration."""

    HIGH = "high"  # Multiple corroborating sources
    MEDIUM = "medium"  # Single reliable source
    LOW = "low"  # Uncorroborated or contested
    CONFLICT = "conflict"  # Sources disagree


class SourceStatus(str, Enum):
    """Status of a source in the verification pipeline."""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIALLY_APPROVED = "partially_approved"


class ClaimStatus(str, Enum):
    """Status of a claim in the verification pipeline."""

    PENDING = "pending"
    VERIFIED = "verified"
    CONTESTED = "contested"
    REJECTED = "rejected"
    USED = "used"  # Claim has been incorporated into draft


class SourceCandidate(BaseModel):
    """A potential source found by the Research Agent.

    This is the raw output from web/academic search before verification.
    """

    id: UUID = Field(default_factory=uuid4)
    url: str
    title: str
    source_type: Literal["academic", "news", "book", "website", "primary", "unknown"]
    snippet: str = ""  # Brief preview from search result
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.5)
    discovered_at: datetime = Field(default_factory=datetime.utcnow)
    query_context: str = ""  # What search/query found this
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        frozen = False


class ApprovedSource(BaseModel):
    """A verified, approved source ready for deep extraction.

    Created by the Verifier Agent after validating credibility and relevance.
    """

    id: UUID = Field(default_factory=uuid4)
    candidate_id: UUID  # Reference to original candidate
    url: str
    title: str
    source_type: Literal["academic", "news", "book", "website", "primary"]
    author: str | None = None
    publication_date: datetime | None = None
    credibility_score: float = Field(ge=0.0, le=1.0, default=0.7)
    content_hash: str = ""  # For de-duplication
    full_text: str | None = None  # Cached content for extraction
    topics_covered: list[str] = Field(default_factory=list)
    verification_notes: str = ""
    approved_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False


class EvidenceSnippet(BaseModel):
    """A specific piece of evidence extracted from a source.

    The atomic unit of supporting evidence for claims.
    """

    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    text: str  # The actual quote or paraphrase
    page_or_section: str | None = None
    context: str = ""  # Surrounding context for clarity
    is_direct_quote: bool = False
    extracted_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False


class Claim(BaseModel):
    """A factual claim with supporting evidence.

    The "anti-hallucination spine" - every fact in the manuscript
    should map to a Claim object with proper citations.
    """

    id: UUID = Field(default_factory=uuid4)
    statement: str  # The claim itself
    evidence_ids: list[UUID] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    status: ClaimStatus = ClaimStatus.PENDING
    topic_tags: list[str] = Field(default_factory=list)
    chapter_assignments: list[str] = Field(default_factory=list)
    conflict_notes: str | None = None
    conflicting_claim_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: datetime | None = None

    class Config:
        frozen = False


class ChapterOutline(BaseModel):
    """High-level structure for a chapter in the outline.

    Part of the hierarchical outline that governs all writing.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_number: int
    title: str
    summary: str = ""  # 2-3 sentence description
    key_topics: list[str] = Field(default_factory=list)
    estimated_word_count: int = 2000
    parent_section: str | None = None  # For nested structure (Part I, etc.)
    subsections: list[str] = Field(default_factory=list)

    class Config:
        frozen = False


class ChapterBrief(BaseModel):
    """Detailed instructions for writing a chapter.

    Created by the Synthesis Agent from verified claims and outline.
    This is the "contract" that constrains the Writer Agent.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_id: UUID
    chapter_number: int
    title: str
    thesis_statement: str = ""
    required_claims: list[UUID] = Field(default_factory=list)  # MUST include
    optional_claims: list[UUID] = Field(default_factory=list)  # MAY include
    key_points: list[str] = Field(default_factory=list)  # Ordered points to make
    transitions: dict[str, str] = Field(default_factory=dict)  # from_chapter -> text
    constraints: list[str] = Field(default_factory=list)  # Style/content constraints
    word_count_target: int = 2000
    word_count_min: int = 1500
    word_count_max: int = 2500
    preceding_context: str = ""  # Summary of what came before
    following_context: str = ""  # What comes after (if known)

    class Config:
        frozen = False


class DraftChunk(BaseModel):
    """A piece of written content from a Writer Agent.

    The atomic unit of generated content before integration.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_id: UUID
    brief_id: UUID
    section_index: int = 0  # Order within chapter
    content: str
    word_count: int = 0
    claims_referenced: list[UUID] = Field(default_factory=list)
    citations_inline: list[str] = Field(default_factory=list)
    style_compliance_score: float = Field(ge=0.0, le=1.0, default=0.8)
    repetition_score: float = Field(ge=0.0, le=1.0, default=0.0)  # Lower is better
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revision_number: int = 0

    class Config:
        frozen = False


class ContentGap(BaseModel):
    """An identified gap in coverage that needs more research.

    Created by the Replanner Agent to trigger new research cycles.
    """

    id: UUID = Field(default_factory=uuid4)
    gap_type: Literal["topic", "evidence", "depth", "perspective", "citation"]
    description: str
    affected_chapters: list[str] = Field(default_factory=list)
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    suggested_queries: list[str] = Field(default_factory=list)
    identified_at: datetime = Field(default_factory=datetime.utcnow)
    resolved: bool = False
    resolution_notes: str = ""

    class Config:
        frozen = False
