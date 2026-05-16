"""Thumbnail generation node - AI generates image with styled text baked in."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from PIL import Image

from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import (
    THUMBNAIL_HOOK_EVAL_SYSTEM,
    THUMBNAIL_HOOK_SYSTEM,
    THUMBNAIL_PROMPT_TEMPLATE,
)
from prolific.youtube.schemas import ThumbnailAsset
from prolific.youtube.services.image_gen import get_image_gen_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


def _build_story_context(state: YouTubePipelineState) -> str:
    """Build a story summary from script sections for thumbnail context."""
    sections = state.get("script_sections", [])
    if not sections:
        return ""

    titles = [s.title for s in sections if s.title]
    key_points = []
    for s in sections[:3]:
        key_points.extend(s.key_points[:2])

    lines = []
    if titles:
        lines.append(f"Story arc: {' → '.join(titles[:6])}")
    if key_points:
        lines.append(f"Key moments: {'; '.join(key_points[:5])}")
    return "\n".join(lines)


async def thumbnail_generation_node(state: YouTubePipelineState) -> dict:
    """Generate a YouTube thumbnail with AI-composed text."""
    logger.info("=== THUMBNAIL GENERATION ===")

    topic = state["topic"]
    is_biography = state.get("is_biography", False)
    thread_id = state["thread_id"]
    style = settings.youtube_image_style
    story_context = _build_story_context(state)

    output_dir = Path(settings.youtube_output_dir) / thread_id
    output_dir.mkdir(parents=True, exist_ok=True)

    service = get_image_gen_service()
    llm_service = get_llm_service()

    # Pull the last 7 thumbnail hooks shipped on this channel so the brainstorm
    # prompt can include them as a DO-NOT-REPEAT list. Without this, the LLM
    # keeps reaching for whatever reference example is most prominent in the
    # system prompt — which is how "WE CAN'T EXPLAIN THIS" shipped 3× in 5 days.
    recent_hooks: list[tuple[str, str]] = []
    try:
        from prolific.youtube.services.channel_history import get_channel_history_service
        history_service = get_channel_history_service()
        await history_service.initialize()
        recent_hooks = await history_service.get_recent_thumbnail_hooks(limit=7)
    except Exception as exc:
        logger.warning(f"Could not load recent thumbnail hooks (non-fatal): {exc}")

    recent_hooks_block = ""
    if recent_hooks:
        lines = [f'  - "{h}"  (topic: {t[:60]})' for h, t in recent_hooks]
        recent_hooks_block = (
            "\n\n═══ RECENTLY-SHIPPED HOOKS ON THIS CHANNEL — DO NOT REPEAT ═══\n"
            "The last few videos shipped with these hooks. Your output MUST be different\n"
            "from ALL of these (case-insensitive). Recycling makes the channel look spammy.\n"
            + "\n".join(lines)
        )

    hook_text = ""
    try:
        hook_prompt = THUMBNAIL_HOOK_SYSTEM.format(
            topic=topic, is_biography=is_biography,
        )
        hook_prompt += recent_hooks_block
        if story_context:
            hook_prompt += f"\n\nSTORY CONTEXT (use this to pick the most dramatic hook):\n{story_context}"

        hook_response = await llm_service.invoke(
            messages=[
                SystemMessage(content=hook_prompt),
                HumanMessage(content="Generate 5 thumbnail hook options."),
            ],
            tier="research",
            temperature=0.9,
        )
        raw_hooks = hook_response.content.strip()
        candidates: list[str] = []
        for line in raw_hooks.split("\n"):
            line = line.strip().lstrip("0123456789.)-: ")
            cleaned = line.strip('"').strip("'").strip().upper()
            if not cleaned or len(cleaned.split()) > 6:
                continue
            # Reject malformed candidates that don't start with a letter — catches
            # the ",000 MILES LOST?" failure mode where the LLM dropped the leading
            # digit during chunked rendering. Also reject too-short outputs.
            if len(cleaned) < 5 or not cleaned[0].isalpha():
                logger.debug(f"Skipping malformed hook candidate: {cleaned!r}")
                continue
            candidates.append(cleaned)
        if not candidates:
            candidates = [raw_hooks.split("\n")[0].strip().upper()]

        logger.info(f"Thumbnail hook candidates: {candidates}")

        class HookEvaluation(BaseModel):
            chosen_index: int = Field(description="0-based index of the best hook")
            rationale: str = Field(description="Why this hook wins")

        candidates_str = "\n".join(f"[{i}] {c}" for i, c in enumerate(candidates))
        eval_user_msg = f"Topic: {topic}\n\nHook candidates:\n{candidates_str}"
        if recent_hooks:
            recent_str = "\n".join(f'  - "{h}"' for h, _ in recent_hooks)
            eval_user_msg += (
                f"\n\nRECENTLY-SHIPPED hooks on this channel (any candidate matching one of these "
                f"verbatim, case-insensitive, must be REJECTED — pick another):\n{recent_str}"
            )
        eval_user_msg += "\n\nPick the best one."
        eval_result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=THUMBNAIL_HOOK_EVAL_SYSTEM),
                HumanMessage(content=eval_user_msg),
            ],
            output_schema=HookEvaluation,
            tier="research",
            temperature=0.3,
        )

        chosen_idx = max(0, min(eval_result.chosen_index, len(candidates) - 1))
        hook_text = candidates[chosen_idx]
        logger.info(f"Thumbnail hook selected: '{hook_text}' (reason: {eval_result.rationale})")
    except Exception as e:
        logger.warning(f"Hook text generation failed, using fallback: {e}")
        hook_text = topic.split(":")[0][:30].upper() if ":" in topic else topic[:30].upper()

    try:
        raw_path = str(output_dir / "thumbnail_raw.png")
        prompt = THUMBNAIL_PROMPT_TEMPLATE.format(
            style=style, topic=topic, hook_text=hook_text,
        )
        if story_context:
            prompt += f"\n\nStory context for choosing the right scene:\n{story_context}"

        await service.generate_image(prompt=prompt, output_path=raw_path)
        logger.info(f"AI thumbnail generated: {raw_path}")

        final_path = str(output_dir / "thumbnail.jpg")
        img = Image.open(raw_path).resize((1280, 720), Image.LANCZOS)
        img.save(final_path, "JPEG", quality=85, optimize=True)
        size_kb = Path(final_path).stat().st_size / 1024
        if size_kb > 2000:
            img.save(final_path, "JPEG", quality=60, optimize=True)
            size_kb = Path(final_path).stat().st_size / 1024
        logger.info(f"Thumbnail compressed: {size_kb:.0f}KB")

        thumbnail = ThumbnailAsset(
            prompt=prompt,
            file_path=final_path,
            title_overlay_text=hook_text,
        )
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        thumbnail = ThumbnailAsset(prompt="", title_overlay_text=hook_text)

    return {
        "thumbnail": thumbnail,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Thumbnail generated: {hook_text}")],
    }
