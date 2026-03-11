"""Thumbnail generation node - creates YouTube thumbnail with text overlay."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import THUMBNAIL_HOOK_SYSTEM, THUMBNAIL_PROMPT_TEMPLATE
from prolific.youtube.schemas import ThumbnailAsset
from prolific.youtube.services.image_gen import get_image_gen_service
from prolific.youtube.services.thumbnail import add_text_overlay
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def thumbnail_generation_node(state: YouTubePipelineState) -> dict:
    """Generate a YouTube thumbnail image with text overlay."""
    logger.info("=== THUMBNAIL GENERATION ===")

    topic = state["topic"]
    is_biography = state.get("is_biography", False)
    thread_id = state["thread_id"]
    style = settings.youtube_image_style

    output_dir = Path(settings.youtube_output_dir) / thread_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "thumbnail.png")

    prompt = THUMBNAIL_PROMPT_TEMPLATE.format(style=style, topic=topic)

    service = get_image_gen_service()
    llm_service = get_llm_service()

    hook_text = ""
    try:
        hook_prompt = THUMBNAIL_HOOK_SYSTEM.format(
            topic=topic, is_biography=is_biography
        )
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
        logger.info(f"Thumbnail hook text: '{hook_text}'")
    except Exception as e:
        logger.warning(f"Hook text generation failed, using fallback: {e}")
        hook_text = topic.split(":")[0][:30] if ":" in topic else topic[:30]

    try:
        await service.generate_image(
            prompt=prompt,
            output_path=output_path,
        )

        if hook_text:
            add_text_overlay(
                image_path=output_path,
                hook_text=hook_text,
                output_path=output_path,
                position="bottom",
            )

        thumbnail = ThumbnailAsset(
            prompt=prompt,
            file_path=output_path,
            title_overlay_text=hook_text,
        )
        logger.info(f"Thumbnail generated: {output_path}")
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        thumbnail = ThumbnailAsset(prompt=prompt)

    return {
        "thumbnail": thumbnail,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Thumbnail generated: {hook_text}")],
    }
