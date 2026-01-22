"""Tests for Pydantic schemas."""

import pytest
from uuid import uuid4

from prolific.schemas.artifacts import (
    Claim,
    ClaimStatus,
    ConfidenceLevel,
    SourceCandidate,
)
from prolific.schemas.memory import GlobalBookMemory, StyleGuide


class TestSourceCandidate:
    """Tests for SourceCandidate schema."""

    def test_create_source_candidate(self):
        """Test creating a source candidate."""
        candidate = SourceCandidate(
            url="https://example.com",
            title="Test",
            source_type="website",
        )
        assert candidate.url == "https://example.com"
        assert candidate.title == "Test"
        assert candidate.relevance_score == 0.5  # default

    def test_source_candidate_with_metadata(self):
        """Test source candidate with metadata."""
        candidate = SourceCandidate(
            url="https://arxiv.org/paper",
            title="Research Paper",
            source_type="academic",
            metadata={"authors": ["Smith"], "year": 2024},
        )
        assert candidate.metadata["authors"] == ["Smith"]


class TestClaim:
    """Tests for Claim schema."""

    def test_create_claim(self):
        """Test creating a claim."""
        source_id = uuid4()
        claim = Claim(
            statement="Test claim statement",
            source_ids=[source_id],
        )
        assert claim.statement == "Test claim statement"
        assert claim.confidence == ConfidenceLevel.LOW  # default
        assert claim.status == ClaimStatus.PENDING  # default

    def test_claim_with_conflict(self):
        """Test claim with conflict notes."""
        claim = Claim(
            statement="Contested claim",
            source_ids=[uuid4()],
            confidence=ConfidenceLevel.CONFLICT,
            conflict_notes="Sources disagree on this point",
        )
        assert claim.confidence == ConfidenceLevel.CONFLICT
        assert claim.conflict_notes is not None


class TestGlobalBookMemory:
    """Tests for GlobalBookMemory schema."""

    def test_create_global_memory(self):
        """Test creating global book memory."""
        memory = GlobalBookMemory(
            title="Test Book",
            target_word_count=50000,
        )
        assert memory.title == "Test Book"
        assert memory.current_word_count == 0

    def test_global_memory_with_style_guide(self):
        """Test global memory with custom style guide."""
        style = StyleGuide(
            tone="conversational",
            use_contractions=True,
        )
        memory = GlobalBookMemory(
            title="Casual Book",
            target_word_count=30000,
            style_guide=style,
        )
        assert memory.style_guide.tone == "conversational"
        assert memory.style_guide.use_contractions is True
