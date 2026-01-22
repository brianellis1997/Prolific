"""Pytest configuration and fixtures."""

import pytest
from uuid import uuid4

from prolific.schemas.artifacts import (
    ApprovedSource,
    Claim,
    ClaimStatus,
    ConfidenceLevel,
    SourceCandidate,
)
from prolific.schemas.memory import GlobalBookMemory, StyleGuide


@pytest.fixture
def sample_source_candidate():
    """Create a sample source candidate for testing."""
    return SourceCandidate(
        id=uuid4(),
        url="https://example.com/article",
        title="Test Article",
        source_type="website",
        snippet="A test article about testing.",
        relevance_score=0.8,
        query_context="test query",
    )


@pytest.fixture
def sample_approved_source(sample_source_candidate):
    """Create a sample approved source for testing."""
    return ApprovedSource(
        id=uuid4(),
        candidate_id=sample_source_candidate.id,
        url=sample_source_candidate.url,
        title=sample_source_candidate.title,
        source_type="website",
        credibility_score=0.85,
        full_text="This is the full text content of the test article.",
    )


@pytest.fixture
def sample_claim(sample_approved_source):
    """Create a sample claim for testing."""
    return Claim(
        id=uuid4(),
        statement="Testing is important for software quality.",
        source_ids=[sample_approved_source.id],
        confidence=ConfidenceLevel.HIGH,
        status=ClaimStatus.VERIFIED,
        topic_tags=["testing", "software"],
    )


@pytest.fixture
def sample_global_memory():
    """Create a sample global book memory for testing."""
    return GlobalBookMemory(
        title="Test Book",
        target_word_count=5000,
        depth_level="standard",
        style_guide=StyleGuide(tone="academic"),
    )
