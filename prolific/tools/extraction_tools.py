"""Extraction tools for Deep Reader/Extractor Agents.

These tools help extract claims, evidence, and structured data
from source documents.
"""

import logging
from uuid import UUID, uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class ExtractedClaim(BaseModel):
    """A claim extracted from source text."""

    statement: str = Field(description="The factual claim statement")
    evidence_quote: str = Field(description="Direct quote or paraphrase supporting the claim")
    confidence: str = Field(description="high, medium, or low based on source clarity")
    topic_tags: list[str] = Field(default_factory=list, description="Relevant topic tags")


class ExtractionResult(BaseModel):
    """Result of claim extraction from a source."""

    claims: list[ExtractedClaim] = Field(default_factory=list)
    key_statistics: list[str] = Field(default_factory=list)
    notable_quotes: list[str] = Field(default_factory=list)


@tool
async def extract_claims_from_text(
    text: str,
    topic_focus: list[str],
    max_claims: int = 20,
) -> list[dict]:
    """Extract factual claims from source text.

    Analyzes the text and extracts discrete factual claims
    that can be verified and cited.

    Args:
        text: Source text to analyze (can be long)
        topic_focus: Topics to focus extraction on
        max_claims: Maximum claims to extract (default 20)

    Returns:
        List of claims with statement, evidence_quote, confidence, topic_tags
    """
    llm_service = get_llm_service()

    system_prompt = """You are an expert research analyst. Extract factual claims from the provided text.

For each claim:
1. State the claim clearly and specifically
2. Include a direct quote or close paraphrase as evidence
3. Assess confidence (high/medium/low) based on how clearly the source states the claim
4. Tag with relevant topics

Focus on claims related to: {topics}

Only extract claims that are:
- Factual and verifiable
- Clearly stated in the text
- Relevant to the focus topics

Return up to {max_claims} claims, prioritizing the most important ones."""

    messages = [
        SystemMessage(content=system_prompt.format(
            topics=", ".join(topic_focus),
            max_claims=max_claims
        )),
        HumanMessage(content=f"Extract claims from this text:\n\n{text[:15000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=ExtractionResult,
            tier="extraction",
            temperature=0.2,
        )

        return [
            {
                "statement": claim.statement,
                "evidence_quote": claim.evidence_quote,
                "confidence": claim.confidence,
                "topic_tags": claim.topic_tags,
            }
            for claim in result.claims
        ]
    except Exception as e:
        logger.error(f"Claim extraction failed: {e}")
        return []


@tool
async def extract_statistics(
    text: str,
) -> list[dict]:
    """Extract numerical data and statistics from text.

    Finds and extracts quantitative claims, percentages,
    measurements, and other numerical data.

    Args:
        text: Source text to analyze

    Returns:
        List of statistics with value, context, and source_quote
    """
    llm_service = get_llm_service()

    system_prompt = """Extract all numerical data, statistics, and quantitative claims from the text.

For each statistic, provide:
1. The numerical value or range
2. What it measures or represents
3. The exact quote from the source
4. Any important context (time period, sample size, etc.)

Focus on concrete numbers, percentages, measurements, and quantitative comparisons."""

    class Statistic(BaseModel):
        value: str
        description: str
        source_quote: str
        context: str = ""

    class StatisticsResult(BaseModel):
        statistics: list[Statistic]

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Extract statistics from:\n\n{text[:15000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=StatisticsResult,
            tier="extraction",
            temperature=0.1,
        )

        return [
            {
                "value": stat.value,
                "description": stat.description,
                "source_quote": stat.source_quote,
                "context": stat.context,
            }
            for stat in result.statistics
        ]
    except Exception as e:
        logger.error(f"Statistics extraction failed: {e}")
        return []


@tool
async def extract_key_quotes(
    text: str,
    topic: str,
    max_quotes: int = 10,
) -> list[dict]:
    """Extract notable quotes relevant to a topic.

    Finds direct quotes that are particularly insightful,
    well-stated, or authoritative on the topic.

    Args:
        text: Source text to analyze
        topic: Topic to focus quote extraction on
        max_quotes: Maximum quotes to extract (default 10)

    Returns:
        List of quotes with text, speaker (if identified), and relevance note
    """
    llm_service = get_llm_service()

    system_prompt = """Find the most notable and quotable passages from this text related to: {topic}

For each quote:
1. Extract the exact quote (use quotation marks)
2. Identify the speaker if mentioned
3. Explain why this quote is notable or useful

Select quotes that are:
- Insightful or well-articulated
- From authoritative voices
- Directly relevant to the topic
- Suitable for citation in an article or book"""

    class Quote(BaseModel):
        text: str
        speaker: str = "Author"
        relevance: str

    class QuotesResult(BaseModel):
        quotes: list[Quote]

    messages = [
        SystemMessage(content=system_prompt.format(topic=topic)),
        HumanMessage(content=f"Extract notable quotes:\n\n{text[:15000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=QuotesResult,
            tier="extraction",
            temperature=0.2,
        )

        return [
            {
                "text": quote.text,
                "speaker": quote.speaker,
                "relevance": quote.relevance,
            }
            for quote in result.quotes[:max_quotes]
        ]
    except Exception as e:
        logger.error(f"Quote extraction failed: {e}")
        return []
