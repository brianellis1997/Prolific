"""Thumbnail generation node - AI generates image with styled text baked in."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from PIL import Image

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import THUMBNAIL_HOOK_SYSTEM, THUMBNAIL_PROMPT_TEMPLATE
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

    hook_text = ""
    try:
        hook_prompt = THUMBNAIL_HOOK_SYSTEM.format(
            topic=topic, is_biography=is_biography,
        )
        if story_context:
            hook_prompt += f"\n\nSTORY CONTEXT (use this to pick the most dramatic hook):\n{story_context}"

        hook_response = await llm_service.invoke(
            messages=[
                SystemMessage(content=hook_prompt),
                HumanMessage(content="Generate the thumbnail hook text."),
            ],
            tier="research",
            temperature=0.7,
        )
        hook_text = hook_response.content.strip().strip('"').strip("'")
        if len(hook_text.split()) > 6:
            hook_text = " ".join(hook_text.split()[:5])
        hook_text = hook_text.upper()
        logger.info(f"Thumbnail hook text: '{hook_text}'")
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
