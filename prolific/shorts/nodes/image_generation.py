"""Image generation node - generates AI images for segments that need them."""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.services.image_gen import ImageGenService
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3


async def _generate_one(
    service: ImageGenService,
    asset: VisualAsset,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> VisualAsset:
    """Generate a single AI image for a visual asset."""
    async with semaphore:
        output_path = str(output_dir / f"image_{asset.sequence_number:02d}.png")
        try:
            style_prefix = settings.shorts_image_style + ". "
            await service.generate_image(
                prompt=asset.image_prompt,
                output_path=output_path,
                style_prefix=style_prefix,
            )
            logger.info(f"[{asset.sequence_number}] Generated AI image")
            return VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="ai_image",
                image_prompt=asset.image_prompt,
                file_path=output_path,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
            )
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Image generation failed: {e}")
            return asset


async def image_generation_node(state: ShortsPipelineState) -> dict:
    """Generate AI images for segments marked as ai_image."""
    logger.info("=== SHORTS: IMAGE GENERATION ===")

    visual_assets = state.get("visual_assets", [])
    image_segments = [a for a in visual_assets if a.asset_type == "ai_image" and not a.file_path]

    if not image_segments:
        logger.info("No AI images to generate")
        return {"current_phase": "tts_generation", "messages": [AIMessage(content="No AI images needed")]}

    service = ImageGenService(model=settings.shorts_image_model)
    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [_generate_one(service, asset, output_dir, semaphore) for asset in image_segments]
    results = await asyncio.gather(*tasks)

    generated_count = sum(1 for r in results if r.file_path)
    logger.info(f"Generated {generated_count}/{len(image_segments)} AI images")

    return {
        "visual_assets": list(results),
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Generated {generated_count} AI images")],
    }
