"""Thumbnail generation node - creates YouTube thumbnail."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.youtube.prompts import THUMBNAIL_PROMPT_TEMPLATE
from prolific.youtube.schemas import ThumbnailAsset
from prolific.youtube.services.image_gen import get_image_gen_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def thumbnail_generation_node(state: YouTubePipelineState) -> dict:
    """Generate a YouTube thumbnail image."""
    logger.info("=== THUMBNAIL GENERATION ===")

    topic = state["topic"]
    thread_id = state["thread_id"]
    style = settings.youtube_image_style

    output_dir = Path(settings.youtube_output_dir) / thread_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "thumbnail.png")

    prompt = THUMBNAIL_PROMPT_TEMPLATE.format(style=style, topic=topic)

    service = get_image_gen_service()

    try:
        await service.generate_image(
            prompt=prompt,
            output_path=output_path,
        )
        thumbnail = ThumbnailAsset(
            prompt=prompt,
            file_path=output_path,
            title_overlay_text=topic[:40],
        )
        logger.info(f"Thumbnail generated: {output_path}")
    except Exception as e:
        logger.error(f"Thumbnail generation failed: {e}")
        thumbnail = ThumbnailAsset(prompt=prompt)

    return {
        "thumbnail": thumbnail,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content="Thumbnail generated")],
    }
