"""Replan node for identifying gaps and routing decisions.

The Replanner Agent analyzes progress, identifies gaps,
and decides whether to continue research or finish.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import ClaimStatus, ContentGap
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class GapAnalysis(BaseModel):
    """Analysis of content gaps."""

    has_critical_gaps: bool
    gaps: list[dict] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)
    recommendation: str = Field(description="continue or finish")


REPLAN_SYSTEM_PROMPT = """You are a content quality analyst reviewing a long-form document in progress.

Topic: {topic}
Target word count: {target_words}
Current word count: {current_words}
Completion: {completion_pct}%

Chapters completed: {chapters_completed}
Verified claims available: {claim_count}
Research iterations so far: {iteration_count} / {max_iterations}

Recent warnings/issues:
{warnings}

Analyze whether:
1. The content adequately covers the topic
2. There are significant gaps in coverage
3. More research is needed
4. We're ready to finalize

Identify specific gaps if any, with priority (critical, high, medium, low).
Suggest search queries for any gaps found."""


async def replan_node(state: ContentGenerationState) -> dict:
    """Analyze progress and decide whether to continue or finish.

    This node:
    1. Evaluates coverage completeness
    2. Identifies content gaps
    3. Generates queries for missing information
    4. Routes to research (continue) or end (finish)

    Args:
        state: Current workflow state

    Returns:
        Dict with content_gaps, needs_replan flag, and routing info
    """
    logger.info("Replan node starting")

    global_memory = state.get("global_memory")
    draft_chunks = state.get("draft_chunks", [])
    claims = state.get("claims", [])
    warnings = state.get("warnings", [])

    verified_claims = [c for c in claims if c.status == ClaimStatus.VERIFIED]
    current_words = sum(chunk.word_count for chunk in draft_chunks)
    target_words = state.get("target_word_count", 50000)
    completion_pct = int((current_words / target_words) * 100) if target_words else 0

    iteration_count = state.get("iteration_count", 0) + 1
    max_iterations = state.get("max_iterations", 5)

    if iteration_count >= max_iterations:
        logger.info(f"Max iterations ({max_iterations}) reached. Finishing.")
        return {
            "iteration_count": iteration_count,
            "needs_replan": False,
            "current_phase": "done",
            "messages": [
                AIMessage(
                    content=f"Max iterations reached. Finalizing at {current_words} words."
                )
            ],
        }

    if completion_pct >= 95:
        logger.info(f"Target word count reached ({completion_pct}%). Finishing.")
        return {
            "iteration_count": iteration_count,
            "needs_replan": False,
            "current_phase": "done",
            "messages": [
                AIMessage(
                    content=f"Target reached ({current_words}/{target_words} words). Done!"
                )
            ],
        }

    llm_service = get_llm_service()

    warnings_text = "\n".join(warnings[-10:]) if warnings else "No warnings."

    system_message = SystemMessage(
        content=REPLAN_SYSTEM_PROMPT.format(
            topic=state["topic"],
            target_words=target_words,
            current_words=current_words,
            completion_pct=completion_pct,
            chapters_completed=len(draft_chunks),
            claim_count=len(verified_claims),
            iteration_count=iteration_count,
            max_iterations=max_iterations,
            warnings=warnings_text,
        )
    )

    subtopics_covered = set()
    for claim in verified_claims:
        subtopics_covered.update(claim.topic_tags)

    subtopics_requested = set(state.get("subtopics", []))
    missing_subtopics = subtopics_requested - subtopics_covered

    user_message = HumanMessage(
        content=f"""Analyze the current progress.

Subtopics requested: {', '.join(subtopics_requested) if subtopics_requested else 'None specified'}
Subtopics covered so far: {', '.join(subtopics_covered) if subtopics_covered else 'None yet'}
Potentially missing: {', '.join(missing_subtopics) if missing_subtopics else 'None identified'}

Should we continue researching or is the content complete enough to finish?"""
    )

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=[system_message, user_message],
            output_schema=GapAnalysis,
            tier="verification",
            temperature=0.3,
        )
    except Exception as e:
        logger.error(f"Gap analysis failed: {e}")
        if completion_pct >= 80:
            return {
                "iteration_count": iteration_count,
                "needs_replan": False,
                "current_phase": "done",
                "messages": [AIMessage(content="Analysis failed but near completion. Finishing.")],
            }
        else:
            return {
                "iteration_count": iteration_count,
                "needs_replan": True,
                "current_phase": "research",
                "messages": [AIMessage(content="Analysis failed. Continuing research.")],
            }

    content_gaps = []
    for gap in result.gaps:
        content_gap = ContentGap(
            gap_type=gap.get("type", "topic"),
            description=gap.get("description", ""),
            priority=gap.get("priority", "medium"),
            suggested_queries=gap.get("queries", result.suggested_queries[:3]),
        )
        content_gaps.append(content_gap)

    should_continue = (
        result.recommendation == "continue"
        and result.has_critical_gaps
        and iteration_count < max_iterations
    )

    if should_continue:
        logger.info(f"Gaps identified. Continuing research (iteration {iteration_count})")
        return {
            "content_gaps": content_gaps,
            "iteration_count": iteration_count,
            "needs_replan": True,
            "current_phase": "research",
            "messages": [
                AIMessage(
                    content=f"Found {len(content_gaps)} gaps. Starting research iteration {iteration_count}."
                )
            ],
        }
    else:
        logger.info(f"Content complete or no critical gaps. Finishing.")
        return {
            "content_gaps": content_gaps,
            "iteration_count": iteration_count,
            "needs_replan": False,
            "current_phase": "done",
            "messages": [
                AIMessage(
                    content=f"Content complete at {current_words} words. "
                    f"{len(content_gaps)} minor gaps noted for future reference."
                )
            ],
        }
