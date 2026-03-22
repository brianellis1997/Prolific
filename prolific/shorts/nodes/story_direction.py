"""Story direction node - unified Director Agent replacing script_writing + visual_planning."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import (
    SegmentDirective,
    ShortScript,
    StoryPlan,
    VisualAsset,
)
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def story_direction_node(state: ShortsPipelineState) -> dict:
    """Director Agent: produce a StoryPlan from clip content analysis.

    Replaces script_writing + visual_planning for clip-based modes.
    Outputs story_plan, script (for downstream compat), and visual_assets.
    """
    logger.info("=== SHORTS: STORY DIRECTION ===")

    topic = state.get("topic", "")
    content_mode = state.get("content_mode", "news_commentary")
    source_clips = state.get("source_clips", [])
    understandings = state.get("clip_content_understanding") or []
    compilation_items = state.get("compilation_items", [])

    logger.info(f"Topic: {topic} | Mode: {content_mode} | Clips: {len(source_clips)}")

    if not source_clips:
        logger.warning("No source clips for story direction — falling back to empty plan")
        return {"current_phase": "failed", "errors": ["No source clips for story direction"]}

    story_angle = ", ".join(compilation_items[:3]) if compilation_items else topic
    review_feedback = state.get("story_review_feedback", "")
    attempt = state.get("story_direction_attempts", 0) + 1

    if review_feedback:
        logger.info(f"Retry attempt {attempt} with feedback: {review_feedback[:100]}")

    clip_summaries = _build_clip_summaries(source_clips, understandings)

    from prolific.shorts.prompts import STORY_DIRECTION_SYSTEM
    prompt = STORY_DIRECTION_SYSTEM.format(
        num_clips=len(source_clips),
        topic=topic,
        story_angle=story_angle,
        clip_summaries=clip_summaries,
    )

    if review_feedback:
        prompt += (
            f"\n\n=== PREVIOUS ATTEMPT WAS REJECTED ===\n"
            f"The quality reviewer gave this feedback:\n{review_feedback}\n\n"
            f"Fix ALL issues listed above. This is attempt {attempt}."
        )

    llm_service = get_llm_service()

    from pydantic import BaseModel, Field

    class SegmentDirectiveOutput(BaseModel):
        sequence_number: int
        mode: str = "narrate"
        narration_text: str = ""
        source_clip_index: int | None = None
        clip_start_seconds: float = 0.0
        clip_duration_seconds: float | None = None
        asset_type: str = "web_image"
        search_query: str = ""
        ken_burns_direction: str = "zoom_in"
        why: str = ""

    class StoryPlanOutput(BaseModel):
        segments: list[SegmentDirectiveOutput] = Field(default_factory=list)
        hook: str = ""

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Direct the story now. Produce the segment list."),
        ],
        output_schema=StoryPlanOutput,
        tier="writing",
        temperature=0.6,
    )

    segments = []
    for seg in result.segments:
        mode = seg.mode if seg.mode in ("narrate", "clip_plays", "narrate_over") else "narrate"
        directive = SegmentDirective(
            sequence_number=seg.sequence_number,
            mode=mode,
            narration_text=seg.narration_text,
            source_clip_index=seg.source_clip_index,
            clip_start_seconds=max(0.0, seg.clip_start_seconds),
            clip_duration_seconds=seg.clip_duration_seconds,
            asset_type=seg.asset_type if seg.asset_type in ("web_image", "stock_clip") else "web_image",
            search_query=seg.search_query,
            ken_burns_direction=seg.ken_burns_direction or "zoom_in",
            why=seg.why,
        )
        segments.append(directive)

    story_plan = StoryPlan(segments=segments, hook=result.hook or "")

    for seg in segments:
        logger.info(
            f"  [{seg.sequence_number}] {seg.mode.upper()}"
            + (f" clip[{seg.source_clip_index}] @{seg.clip_start_seconds:.0f}s"
               f" for {seg.clip_duration_seconds:.0f}s"
               if seg.source_clip_index is not None and seg.clip_duration_seconds else "")
            + (f" | \"{seg.narration_text[:50]}\"" if seg.narration_text else "")
            + f" | WHY: {seg.why[:60]}"
        )

    script = _derive_script(story_plan)
    visual_assets = _derive_visual_assets(story_plan, source_clips)

    stock_count = sum(1 for a in visual_assets if a.asset_type == "stock_clip")
    web_count = sum(1 for a in visual_assets if a.asset_type == "web_image")
    source_count = sum(1 for a in visual_assets if a.asset_type == "source_clip")
    logger.info(
        f"Story plan: {len(segments)} segments "
        f"({sum(1 for s in segments if s.mode == 'clip_plays')} clip_plays, "
        f"{sum(1 for s in segments if s.mode == 'narrate_over')} narrate_over, "
        f"{sum(1 for s in segments if s.mode == 'narrate')} narrate)"
    )
    logger.info(f"Visual assets: {stock_count} stock, {web_count} web, {source_count} source")

    return {
        "story_plan": story_plan,
        "script": script,
        "visual_assets": visual_assets,
        "current_phase": "asset_generation",
        "messages": [AIMessage(content=f"Story directed: {len(segments)} segments")],
    }


def _build_clip_summaries(source_clips: list, understandings: list) -> str:
    parts = []
    for i, clip in enumerate(source_clips):
        u = understandings[i] if i < len(understandings) else None
        lines = [f"CLIP {i} ({clip.platform.upper()}) — {clip.clip_title or 'untitled'}"]
        lines.append(f"  Creator: {clip.creator_name or 'unknown'}")
        lines.append(f"  Duration: {clip.duration_seconds:.0f}s")
        if clip.file_path:
            lines.append(f"  Downloaded: yes")
        if u:
            if u.clip_duration_seconds > 0:
                lines.append(f"  Analyzed duration: {u.clip_duration_seconds:.1f}s")
            if u.content_summary:
                lines.append(f"  Content: {u.content_summary}")
            if u.visual_analysis:
                va = u.visual_analysis
                if va.people_visible:
                    lines.append(f"  People: {', '.join(va.people_visible)}")
                if va.emotional_tone:
                    lines.append(f"  Tone: {va.emotional_tone}")
                if va.visual_summary:
                    lines.append(f"  Visual: {va.visual_summary}")
            if u.key_moments:
                moments_str = " | ".join(u.key_moments[:4])
                lines.append(f"  Key moments: {moments_str}")
            if u.transcript:
                lines.append(f"  Transcript (first 200 chars): {u.transcript[:200]}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _derive_script(story_plan: StoryPlan) -> ShortScript:
    narration_parts = [
        seg.narration_text
        for seg in story_plan.segments
        if seg.narration_text and seg.mode in ("narrate", "narrate_over")
    ]
    full_text = " ".join(narration_parts).strip()
    word_count = len(full_text.split()) if full_text else 0

    hook = story_plan.hook or (narration_parts[0] if narration_parts else "")

    return ShortScript(
        hook=hook,
        setup="",
        value_body="",
        cta_loop="",
        full_text=full_text,
        word_count=word_count,
        visual_suggestions=[seg.search_query for seg in story_plan.segments if seg.search_query],
    )


def _derive_visual_assets(story_plan: StoryPlan, source_clips: list) -> list[VisualAsset]:
    assets = []
    for seg in story_plan.segments:
        if seg.mode in ("clip_plays", "narrate_over"):
            clip_idx = seg.source_clip_index or 0
            clip = source_clips[clip_idx] if clip_idx < len(source_clips) else None
            if not clip or not clip.file_path:
                continue
            duration = seg.clip_duration_seconds or clip.duration_seconds or 8.0
            assets.append(VisualAsset(
                sequence_number=seg.sequence_number,
                asset_type="source_clip",
                search_query=clip.clip_title or "",
                file_path=clip.file_path,
                duration_seconds=duration,
                script_text=seg.narration_text if seg.mode == "narrate_over" else "",
            ))
        else:
            assets.append(VisualAsset(
                sequence_number=seg.sequence_number,
                asset_type=seg.asset_type,
                search_query=seg.search_query,
                image_prompt="",
                duration_seconds=max(2.0, len(seg.narration_text.split()) / 2.5) if seg.narration_text else 4.0,
                ken_burns_direction=seg.ken_burns_direction,
                script_text=seg.narration_text,
            ))
    return sorted(assets, key=lambda a: a.sequence_number)
