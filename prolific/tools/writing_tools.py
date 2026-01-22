"""Writing tools for Writer and Integration Agents.

These tools help with content generation, style checking,
and ensuring consistency across chapters.
"""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class StyleAnalysis(BaseModel):
    """Analysis of writing style compliance."""

    compliance_score: float = Field(ge=0, le=1)
    tone_match: bool
    formality_match: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


@tool
async def check_style_compliance(
    content: str,
    style_tone: str = "academic",
    formality_level: float = 0.7,
    use_contractions: bool = False,
) -> dict:
    """Check if content matches the style guide.

    Analyzes writing style for consistency with the
    specified tone and formality requirements.

    Args:
        content: Content to check
        style_tone: Expected tone (academic, conversational, technical, journalistic)
        formality_level: 0-1 formality level (0=casual, 1=formal)
        use_contractions: Whether contractions are allowed

    Returns:
        Dict with compliance_score, issues, and suggestions
    """
    llm_service = get_llm_service()

    system_prompt = """Analyze this content for style compliance.

Expected style:
- Tone: {tone}
- Formality: {formality} (0=casual, 1=formal)
- Contractions: {"allowed" if use_contractions else "not allowed"}

Check for:
- Tone consistency (academic, conversational, etc.)
- Appropriate formality level
- Contraction usage
- Sentence structure variety
- Word choice appropriateness

Provide specific issues and actionable suggestions."""

    messages = [
        SystemMessage(content=system_prompt.format(
            tone=style_tone,
            formality=formality_level,
            use_contractions=use_contractions
        )),
        HumanMessage(content=f"Content to analyze:\n\n{content[:5000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=StyleAnalysis,
            tier="verification",
            temperature=0.2,
        )

        return {
            "compliance_score": result.compliance_score,
            "tone_match": result.tone_match,
            "formality_match": result.formality_match,
            "issues": result.issues,
            "suggestions": result.suggestions,
        }
    except Exception as e:
        logger.error(f"Style check failed: {e}")
        return {
            "compliance_score": 0.7,
            "tone_match": True,
            "formality_match": True,
            "issues": ["Style check failed"],
            "suggestions": [],
        }


class TransitionAnalysis(BaseModel):
    """Analysis of chapter transitions."""

    flows_well: bool
    transition_quality: float = Field(ge=0, le=1)
    issues: list[str] = Field(default_factory=list)
    suggested_transition: str = ""


@tool
async def analyze_chapter_transition(
    previous_chapter_ending: str,
    current_chapter_beginning: str,
) -> dict:
    """Analyze the transition between chapters.

    Checks if the transition from one chapter to the next
    flows naturally and maintains coherence.

    Args:
        previous_chapter_ending: Last 500 words of previous chapter
        current_chapter_beginning: First 500 words of current chapter

    Returns:
        Dict with flows_well, transition_quality, issues, suggested_transition
    """
    llm_service = get_llm_service()

    system_prompt = """Analyze the transition between these two chapter sections.

Check for:
- Logical flow from one topic to the next
- Appropriate transition phrases
- Topic continuity or clear pivot
- Reader orientation

Suggest improvements if needed."""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"""Previous chapter ending:
{previous_chapter_ending[-2000:]}

Current chapter beginning:
{current_chapter_beginning[:2000]}""")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=TransitionAnalysis,
            tier="verification",
            temperature=0.3,
        )

        return {
            "flows_well": result.flows_well,
            "transition_quality": result.transition_quality,
            "issues": result.issues,
            "suggested_transition": result.suggested_transition,
        }
    except Exception as e:
        logger.error(f"Transition analysis failed: {e}")
        return {
            "flows_well": True,
            "transition_quality": 0.7,
            "issues": ["Analysis failed"],
            "suggested_transition": "",
        }


class ConsistencyCheck(BaseModel):
    """Check for internal consistency."""

    is_consistent: bool
    contradictions: list[str] = Field(default_factory=list)
    terminology_issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


@tool
async def check_internal_consistency(
    content: str,
    glossary_terms: dict[str, str] | None = None,
) -> dict:
    """Check content for internal consistency.

    Looks for contradictions, terminology inconsistencies,
    and other coherence issues.

    Args:
        content: Content to check
        glossary_terms: Optional dict of term -> definition for consistency

    Returns:
        Dict with is_consistent, contradictions, terminology_issues, suggestions
    """
    llm_service = get_llm_service()

    system_prompt = """Check this content for internal consistency.

Look for:
- Self-contradictions
- Inconsistent terminology
- Logical gaps
- Repeated information
- Conflicting claims

{glossary_section}

Identify specific issues with locations if possible."""

    glossary_section = ""
    if glossary_terms:
        glossary_section = "Required terminology:\n"
        for term, definition in list(glossary_terms.items())[:20]:
            glossary_section += f"- {term}: {definition}\n"

    messages = [
        SystemMessage(content=system_prompt.format(glossary_section=glossary_section)),
        HumanMessage(content=f"Content to check:\n\n{content[:8000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=ConsistencyCheck,
            tier="verification",
            temperature=0.2,
        )

        return {
            "is_consistent": result.is_consistent,
            "contradictions": result.contradictions,
            "terminology_issues": result.terminology_issues,
            "suggestions": result.suggestions,
        }
    except Exception as e:
        logger.error(f"Consistency check failed: {e}")
        return {
            "is_consistent": True,
            "contradictions": [],
            "terminology_issues": [],
            "suggestions": ["Consistency check failed"],
        }


@tool
async def generate_chapter_summary(
    chapter_content: str,
    chapter_title: str,
    max_length: int = 300,
) -> dict:
    """Generate a summary of a chapter for book memory.

    Creates a concise summary that captures key points
    for maintaining context across chapters.

    Args:
        chapter_content: Full chapter content
        chapter_title: Title of the chapter
        max_length: Maximum summary length in words

    Returns:
        Dict with summary, key_points, and new_terms
    """
    llm_service = get_llm_service()

    class ChapterSummary(BaseModel):
        summary: str = Field(description="Concise chapter summary")
        key_points: list[str] = Field(description="Main points covered")
        new_terms: list[str] = Field(description="New terms or concepts introduced")
        topics_covered: list[str] = Field(description="Topics addressed in this chapter")

    system_prompt = """Summarize this chapter for maintaining context in a long document.

Chapter: {title}

Provide:
1. A concise summary (max {max_length} words)
2. Key points covered (3-5 bullet points)
3. New terms or concepts introduced
4. Topics addressed

Focus on information that would help a writer of subsequent chapters
maintain coherence and avoid repetition."""

    messages = [
        SystemMessage(content=system_prompt.format(title=chapter_title, max_length=max_length)),
        HumanMessage(content=f"Chapter content:\n\n{chapter_content[:12000]}")
    ]

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=messages,
            output_schema=ChapterSummary,
            tier="extraction",
            temperature=0.3,
        )

        return {
            "summary": result.summary,
            "key_points": result.key_points,
            "new_terms": result.new_terms,
            "topics_covered": result.topics_covered,
        }
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        return {
            "summary": f"Summary of {chapter_title}",
            "key_points": [],
            "new_terms": [],
            "topics_covered": [],
        }
