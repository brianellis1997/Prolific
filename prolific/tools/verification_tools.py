"""Verification tools for the Verifier and Cross-Check Agents.

These tools help verify source credibility, check claim accuracy,
and detect conflicts between sources.
"""

import logging
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class CredibilityAssessment(BaseModel):
    """Assessment of source credibility."""

    credibility_score: float = Field(ge=0, le=1, description="0-1 credibility score")
    source_type: str = Field(description="academic, news, blog, official, unknown")
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    recommendation: str = Field(description="approve, reject, or partially_approve")


@tool
async def assess_source_credibility(
    url: str,
    title: str,
    snippet: str,
    content_preview: str = "",
) -> dict:
    """Assess the credibility of a source.

    Evaluates the source based on domain reputation, content quality,
    and other credibility signals.

    Args:
        url: Source URL
        title: Source title
        snippet: Brief snippet or description
        content_preview: Optional preview of content (first 1000 chars)

    Returns:
        Dict with credibility_score, source_type, strengths, concerns, recommendation
    """
    llm_service = get_llm_service()

    today = datetime.now().strftime("%B %d, %Y")
    system_prompt = f"""You are an expert fact-checker assessing source credibility.

IMPORTANT: Today's date is {today}. Your training data may be outdated. When evaluating sources:
- Do NOT reject sources because they mention products, events, or research you are unfamiliar with.
- Do NOT flag publication dates as "in the future" if they fall before today's date.
- These sources were found via live web search and reflect real, current information.
- Judge credibility based on the SOURCE SIGNALS (domain reputation, author credentials, citation quality, internal consistency), NOT on whether the content matches your training data.

Evaluate this source and provide:
1. A credibility score (0-1):
   - 0.9-1.0: Peer-reviewed, primary sources, authoritative institutions
   - 0.7-0.9: Reputable news, well-known experts, official documents
   - 0.5-0.7: Secondary sources, general websites with citations
   - 0.3-0.5: Opinion pieces, blogs without citations
   - 0.0-0.3: Unknown sources, clear bias, factual errors

2. Source type classification

3. Specific strengths (what makes it credible)

4. Concerns (potential issues - focus on source quality, NOT on whether you recognize the subject matter)

5. Recommendation: approve (use freely), partially_approve (use with caution), reject (don't use)"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""Assess this source:

URL: {url}
Title: {title}
Snippet: {snippet}
Content Preview: {content_preview[:2000] if content_preview else 'Not available'}""")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=CredibilityAssessment,
            tier="verification",
            temperature=0.2,
        )

        return {
            "credibility_score": result.credibility_score,
            "source_type": result.source_type,
            "strengths": result.strengths,
            "concerns": result.concerns,
            "recommendation": result.recommendation,
        }
    except Exception as e:
        logger.error(f"Credibility assessment failed: {e}")
        return {
            "credibility_score": 0.5,
            "source_type": "unknown",
            "strengths": [],
            "concerns": ["Assessment failed"],
            "recommendation": "partially_approve",
        }


@tool
async def check_source_recency(
    publish_date: str | None,
    topic: str,
) -> dict:
    """Check if a source is recent enough for the topic.

    Some topics require very recent sources (e.g., technology, current events)
    while others are fine with older sources (e.g., history, philosophy).

    Args:
        publish_date: Publication date as ISO string (or None if unknown)
        topic: The topic being researched

    Returns:
        Dict with is_current, staleness_risk, recommendation
    """
    if not publish_date:
        return {
            "is_current": None,
            "staleness_risk": "unknown",
            "recommendation": "Verify publication date before relying on this source",
        }

    try:
        pub_date = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
        age_days = (datetime.now(pub_date.tzinfo) - pub_date).days
    except Exception:
        return {
            "is_current": None,
            "staleness_risk": "unknown",
            "recommendation": "Could not parse publication date",
        }

    llm_service = get_llm_service()

    class RecencyAssessment(BaseModel):
        is_current: bool
        staleness_risk: str = Field(description="none, low, medium, high")
        recommendation: str

    today_str = datetime.now().strftime("%B %d, %Y")
    system_prompt = """Assess if a source's age is appropriate for the topic.

Today's date: """ + today_str + """
Source age: {age_days} days (published {pub_date})
Topic: {topic}

Consider:
- Technology topics: sources older than 1-2 years may be outdated
- Current events: sources should be very recent
- Science: check if the field moves quickly
- History/Philosophy: older sources may be fine
- Statistics/Data: check if more recent data might exist

IMPORTANT: Do NOT flag sources as "future-dated" if their publication date is before today."""

    messages = [
        SystemMessage(content=system_prompt.format(
            age_days=age_days,
            pub_date=publish_date,
            topic=topic
        )),
        HumanMessage(content="Assess the recency appropriateness.")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=RecencyAssessment,
            tier="verification",
            temperature=0.2,
        )

        return {
            "is_current": result.is_current,
            "staleness_risk": result.staleness_risk,
            "recommendation": result.recommendation,
            "age_days": age_days,
        }
    except Exception as e:
        logger.error(f"Recency check failed: {e}")
        return {
            "is_current": age_days < 365,
            "staleness_risk": "low" if age_days < 365 else "medium",
            "recommendation": "Manual review recommended",
            "age_days": age_days,
        }


class ConflictAnalysis(BaseModel):
    """Analysis of conflicts between claims."""

    has_conflict: bool
    conflict_type: str = Field(description="direct, partial, or none")
    conflict_description: str
    resolution_suggestion: str


@tool
async def detect_claim_conflicts(
    claim1: str,
    claim1_source: str,
    claim2: str,
    claim2_source: str,
) -> dict:
    """Detect if two claims conflict with each other.

    Analyzes whether claims from different sources contradict
    each other and suggests resolution.

    Args:
        claim1: First claim statement
        claim1_source: Source of first claim
        claim2: Second claim statement
        claim2_source: Source of second claim

    Returns:
        Dict with has_conflict, conflict_type, conflict_description, resolution_suggestion
    """
    llm_service = get_llm_service()

    system_prompt = """Analyze whether these two claims conflict.

Claim 1 (from {source1}): {claim1}
Claim 2 (from {source2}): {claim2}

Determine:
1. Do they conflict? (direct contradiction, partial disagreement, or no conflict)
2. What specifically is the conflict?
3. How might this be resolved? (one is newer/more authoritative, they're measuring different things, etc.)"""

    messages = [
        SystemMessage(content=system_prompt.format(
            source1=claim1_source,
            claim1=claim1,
            source2=claim2_source,
            claim2=claim2
        )),
        HumanMessage(content="Analyze these claims for conflicts.")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=ConflictAnalysis,
            tier="verification",
            temperature=0.2,
        )

        return {
            "has_conflict": result.has_conflict,
            "conflict_type": result.conflict_type,
            "conflict_description": result.conflict_description,
            "resolution_suggestion": result.resolution_suggestion,
        }
    except Exception as e:
        logger.error(f"Conflict detection failed: {e}")
        return {
            "has_conflict": False,
            "conflict_type": "none",
            "conflict_description": "Analysis failed",
            "resolution_suggestion": "Manual review needed",
        }


@tool
async def verify_claim_against_source(
    claim: str,
    source_text: str,
) -> dict:
    """Verify that a claim accurately represents its source.

    Checks if the claim is a fair representation of what
    the source actually says.

    Args:
        claim: The claim to verify
        source_text: Original source text

    Returns:
        Dict with is_accurate, accuracy_score, issues, suggested_correction
    """
    llm_service = get_llm_service()

    class AccuracyAssessment(BaseModel):
        is_accurate: bool
        accuracy_score: float = Field(ge=0, le=1)
        issues: list[str] = Field(default_factory=list)
        suggested_correction: str = ""

    today_str = datetime.now().strftime("%B %d, %Y")
    system_prompt = f"""Verify if this claim accurately represents the source.

Today's date: {today_str}. Your training data may not cover recent events. Judge accuracy based on whether the claim faithfully represents the SOURCE TEXT provided, not on your prior knowledge.

Claim: {{claim}}

Check for:
- Misquotation or paraphrasing errors
- Taking statements out of context
- Overgeneralization
- Missing important qualifiers
- Whether the claim matches what the source text actually says

Provide an accuracy score (0-1) and any issues found."""

    messages = [
        SystemMessage(content=system_prompt.format(claim=claim)),
        HumanMessage(content=f"Source text:\n\n{source_text[:10000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=AccuracyAssessment,
            tier="verification",
            temperature=0.2,
        )

        return {
            "is_accurate": result.is_accurate,
            "accuracy_score": result.accuracy_score,
            "issues": result.issues,
            "suggested_correction": result.suggested_correction,
        }
    except Exception as e:
        logger.error(f"Claim verification failed: {e}")
        return {
            "is_accurate": True,
            "accuracy_score": 0.5,
            "issues": ["Verification failed"],
            "suggested_correction": "",
        }
