"""Story review node - quality gate that evaluates story plans before proceeding."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)

MAX_STORY_ATTEMPTS = 3

STORY_REVIEW_PROMPT = """You are a senior video editor reviewing a story plan for a YouTube Short
before it goes to production. Your job is to catch BAD content that would embarrass the channel.

TOPIC: {topic}
STORY ANGLE: {story_angle}

=== CLIPS AVAILABLE ===
{clip_summaries}

=== STORY PLAN TO REVIEW ===
{story_plan_text}

=== REVIEW CRITERIA ===

Score each dimension 1-5 and provide specific feedback:

1. **COHERENCE** (1-5): Does the story make sense? Are clips related to each other and
   the topic? Or are they random/disconnected clips forced into a fake narrative?
   - 1 = clips have nothing to do with each other
   - 3 = loosely related, some connections feel forced
   - 5 = all clips clearly tell one story

2. **CLIP MOMENTS** (1-5): Are the clip_plays moments well-chosen? Do they show the
   actual dramatic/interesting moment, or random timestamps?
   - 1 = clip_start_seconds seem random, no connection to key moments
   - 3 = some moments are good, some are clearly wrong
   - 5 = every clip_plays shows the exact money moment

3. **NARRATION FLOW** (1-5): Does the narration build a story arc? Hook → setup →
   payoff → closer? Or is it disjointed random sentences?
   - 1 = narration is generic/disconnected from clips
   - 3 = narration tells a story but transitions are awkward
   - 5 = narration flows naturally, each segment builds on the last

4. **VISUAL MATCH** (1-5): Do the visuals match what's being said? When narrating
   about a specific person, do we see that person (in a clip or relevant image)?
   - 1 = visuals are random/unrelated to narration
   - 3 = some visuals match, some don't
   - 5 = every visual perfectly matches the narration

Return:
- approved: true/false (approved if ALL scores are 3+ and average is 3.5+)
- overall_score: average of the 4 scores
- feedback: Specific actionable feedback for the Director Agent if rejected.
  Tell it EXACTLY what to fix: which segments are wrong, which clips to use
  differently, what narration to rewrite. Be specific, not vague."""


class StoryReviewResult(BaseModel):
    approved: bool = False
    overall_score: float = 0.0
    feedback: str = ""


async def story_review_node(state: ShortsPipelineState) -> dict:
    """Review story plan quality. Approve or reject with feedback for retry."""
    logger.info("=== SHORTS: STORY REVIEW ===")

    story_plan = state.get("story_plan")
    if not story_plan:
        return {"current_phase": "failed", "errors": ["No story plan to review"]}

    attempts = state.get("story_direction_attempts", 0) + 1
    topic = state.get("topic", "")
    source_clips = state.get("source_clips", [])
    understandings = state.get("clip_content_understanding") or []

    story_plan_lines = []
    for seg in story_plan.segments:
        line = f"  [{seg.sequence_number}] {seg.mode.upper()}"
        if seg.source_clip_index is not None:
            line += f" clip[{seg.source_clip_index}]"
            if seg.clip_start_seconds:
                line += f" @{seg.clip_start_seconds:.0f}s"
            if seg.clip_duration_seconds:
                line += f" for {seg.clip_duration_seconds:.0f}s"
        if seg.narration_text:
            line += f' | "{seg.narration_text}"'
        if seg.search_query:
            line += f" | image: {seg.search_query}"
        if seg.why:
            line += f" | WHY: {seg.why}"
        story_plan_lines.append(line)
    story_plan_text = "\n".join(story_plan_lines)

    from prolific.shorts.nodes.story_direction import _build_clip_summaries
    clip_summaries = _build_clip_summaries(source_clips, understandings)

    compilation_items = state.get("compilation_items", [])
    story_angle = ", ".join(compilation_items[:3]) if compilation_items else topic

    llm_service = get_llm_service()
    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=STORY_REVIEW_PROMPT.format(
                topic=topic,
                story_angle=story_angle,
                clip_summaries=clip_summaries,
                story_plan_text=story_plan_text,
            )),
            HumanMessage(content="Review this story plan now. Be critical."),
        ],
        output_schema=StoryReviewResult,
        tier="research",
        temperature=0.2,
    )

    logger.info(f"Review score: {result.overall_score:.1f}/5.0 | Approved: {result.approved}")
    if result.feedback:
        logger.info(f"Feedback: {result.feedback[:200]}")

    if result.approved or attempts >= MAX_STORY_ATTEMPTS:
        if not result.approved:
            logger.warning(f"Story plan not approved after {attempts} attempts, proceeding anyway")
        return {
            "story_direction_attempts": attempts,
            "current_phase": "asset_generation",
            "messages": [AIMessage(
                content=f"Story {'approved' if result.approved else 'accepted (max retries)'} "
                f"(score: {result.overall_score:.1f}/5, attempt {attempts})"
            )],
        }
    else:
        logger.info(f"Story rejected (attempt {attempts}/{MAX_STORY_ATTEMPTS}), retrying with feedback")
        return {
            "story_direction_attempts": attempts,
            "story_review_feedback": result.feedback,
            "story_plan": None,
            "visual_assets": [],
            "current_phase": "story_direction",
            "messages": [AIMessage(
                content=f"Story rejected (score: {result.overall_score:.1f}/5, attempt {attempts}): {result.feedback[:100]}"
            )],
        }
