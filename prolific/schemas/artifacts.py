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


class PartOutline(BaseModel):
    """Top-level division of a long document (e.g., Part I, Part II).

    For documents >50k words, parts provide thematic grouping of chapters.
    Shorter documents may have no parts (just chapters).
    """

    id: UUID = Field(default_factory=uuid4)
    part_number: int
    title: str
    theme: str = ""  # Overarching theme of this part
    summary: str = ""  # 2-3 sentence description
    chapter_ids: list[UUID] = Field(default_factory=list)
    estimated_word_count: int = 20000
    key_themes: list[str] = Field(default_factory=list)

    class Config:
        frozen = False


class SectionOutline(BaseModel):
    """A section within a chapter.

    Chapters are divided into sections for better organization
    and to keep each writing unit within manageable context limits.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_id: UUID
    section_number: int  # 1-indexed within chapter
    title: str
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    estimated_word_count: int = 2000
    claim_ids: list[UUID] = Field(default_factory=list)  # Claims to cover in this section

    class Config:
        frozen = False


class ChapterOutline(BaseModel):
    """High-level structure for a chapter in the outline.

    Part of the hierarchical outline that governs all writing.
    """

    id: UUID = Field(default_factory=uuid4)
    part_id: UUID | None = None  # Reference to parent part (None for short docs)
    chapter_number: int
    title: str
    summary: str = ""  # 2-3 sentence description
    key_topics: list[str] = Field(default_factory=list)
    estimated_word_count: int = 5000  # Increased default for longer chapters
    section_ids: list[UUID] = Field(default_factory=list)  # Ordered section references

    class Config:
        frozen = False


class ChapterBrief(BaseModel):
    """Detailed instructions for writing a chapter.

    Created by the Synthesis Agent from verified claims and outline.
    This is the "contract" that constrains the Writer Agent.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_id: UUID
    part_id: UUID | None = None  # Reference to parent part
    chapter_number: int
    title: str
    thesis_statement: str = ""
    required_claims: list[UUID] = Field(default_factory=list)  # MUST include
    optional_claims: list[UUID] = Field(default_factory=list)  # MAY include
    key_points: list[str] = Field(default_factory=list)  # Ordered points to make
    section_briefs: list["SectionBrief"] = Field(default_factory=list)  # Nested sections
    transitions: dict[str, str] = Field(default_factory=dict)  # from_chapter -> text
    constraints: list[str] = Field(default_factory=list)  # Style/content constraints
    word_count_target: int = 5000  # Increased for longer chapters
    word_count_min: int = 4000
    word_count_max: int = 8000
    preceding_context: str = ""  # Summary of what came before
    following_context: str = ""  # What comes after (if known)

    class Config:
        frozen = False


class SectionBrief(BaseModel):
    """Detailed instructions for writing a section within a chapter.

    Sections are the atomic writing unit - small enough for focused context
    but large enough to develop ideas properly.
    """

    id: UUID = Field(default_factory=uuid4)
    section_id: UUID
    chapter_id: UUID
    section_number: int  # 1-indexed within chapter
    title: str
    key_points: list[str] = Field(default_factory=list)
    required_claims: list[UUID] = Field(default_factory=list)
    claim_urls: dict[str, str] = Field(default_factory=dict)  # claim_id -> source_url for hyperlinks
    word_count_target: int = 2000
    word_count_min: int = 1500
    word_count_max: int = 2500
    transition_from_previous: str = ""  # How to connect from previous section
    transition_to_next: str = ""  # How to lead into next section

    class Config:
        frozen = False


class DraftChunk(BaseModel):
    """A piece of written content from a Writer Agent.

    The atomic unit of generated content before integration.
    """

    id: UUID = Field(default_factory=uuid4)
    part_id: UUID | None = None  # Reference to parent part
    chapter_id: UUID
    section_id: UUID | None = None  # Reference to section (if using sections)
    brief_id: UUID
    section_index: int = 0  # Order within chapter
    content: str
    word_count: int = 0
    claims_referenced: list[UUID] = Field(default_factory=list)
    citations_inline: list[str] = Field(default_factory=list)
    hyperlinks_used: list[str] = Field(default_factory=list)  # URLs linked in content
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


class VisualType(str, Enum):
    """Types of visual assets."""

    IMAGE_WEB = "image_web"  # Retrieved from the web
    IMAGE_GENERATED = "image_generated"  # AI-generated
    PLOT = "plot"  # Data visualization (matplotlib, seaborn)
    DIAGRAM = "diagram"  # Flowchart, architecture diagram
    TABLE = "table"  # Data table


class VisualPurpose(str, Enum):
    """Purpose of a visual in the content."""

    EXPLAIN = "explain"  # Explain a concept
    COMPARE = "compare"  # Compare options/data
    SHOW_TREND = "show_trend"  # Display data trends
    ILLUSTRATE = "illustrate"  # Add visual interest
    EVIDENCE = "evidence"  # Support a claim with data


class VisualIntent(BaseModel):
    """Describes a visual that should be created/retrieved.

    Created by Visual Planner to specify what visual is needed.
    """

    id: UUID = Field(default_factory=uuid4)
    chapter_id: UUID
    section_index: int = 0
    placement_hint: str = ""  # e.g., "after paragraph 3"

    visual_type: VisualType
    purpose: VisualPurpose
    description: str  # What the visual should show
    search_queries: list[str] = Field(default_factory=list)  # For web retrieval

    related_claims: list[UUID] = Field(default_factory=list)
    data_requirements: dict[str, Any] = Field(default_factory=dict)

    priority: Literal["required", "recommended", "optional"] = "recommended"
    style_constraints: list[str] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False


class FigureSpec(BaseModel):
    """Specification for generating a data plot.

    Used by Plot Generator to create matplotlib/seaborn visualizations.
    """

    id: UUID = Field(default_factory=uuid4)
    intent_id: UUID  # Reference to VisualIntent

    chart_type: Literal[
        "line", "bar", "scatter", "histogram", "heatmap",
        "pie", "box", "area", "timeline"
    ]
    title: str
    x_label: str = ""
    y_label: str = ""

    data_source: Literal["claim_data", "external_url", "inline", "synthetic"]
    data: dict[str, Any] = Field(default_factory=dict)  # Inline data
    data_url: str | None = None  # External data source

    aggregation: str | None = None  # e.g., "sum", "mean", "count"
    filters: dict[str, Any] = Field(default_factory=dict)

    style_theme: str = "default"  # matplotlib/seaborn theme
    color_palette: str | None = None
    figure_size: tuple[int, int] = (10, 6)

    code_language: Literal["python"] = "python"
    generated_code: str | None = None

    class Config:
        frozen = False


class VisualAsset(BaseModel):
    """A generated or retrieved visual asset.

    The final visual that can be inserted into the content.
    """

    id: UUID = Field(default_factory=uuid4)
    intent_id: UUID  # Reference to VisualIntent
    figure_spec_id: UUID | None = None  # If from FigureSpec

    visual_type: VisualType
    source: Literal["generated", "web", "plot"]

    file_path: str | None = None  # Local path to image
    url: str | None = None  # Original URL if from web
    base64_data: str | None = None  # Inline image data

    caption: str = ""
    alt_text: str = ""

    width: int | None = None
    height: int | None = None
    format: Literal["png", "svg", "jpg", "webp"] = "png"

    provenance: dict[str, Any] = Field(default_factory=dict)
    license_info: str | None = None
    attribution: str | None = None

    quality_score: float = Field(ge=0.0, le=1.0, default=0.7)
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.7)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False


class QualityIssue(BaseModel):
    """A quality issue identified during integration.

    Used for tracking and auto-remediation of content issues.
    """

    id: UUID = Field(default_factory=uuid4)
    issue_type: Literal[
        "repetition", "missing_citation", "style_mismatch",
        "contradiction", "poor_transition", "factual_error",
        "unclear_writing", "missing_context"
    ]
    severity: Literal["critical", "major", "minor"] = "minor"
    description: str

    location_chapter_id: UUID | None = None
    location_section: str | None = None
    location_text: str | None = None  # Snippet of problematic text

    suggested_fix: str = ""
    auto_fixable: bool = False
    fix_applied: bool = False

    confidence: float = Field(ge=0.0, le=1.0, default=0.7)
    identified_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = False
