"""Image generation node - generates images using Nano Banana 2."""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.youtube.schemas import ImageAsset
from prolific.youtube.services.image_gen import get_image_gen_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3


async def _generate_single_image(
    asset: ImageAsset,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> ImageAsset:
    """Generate a single image with concurrency control."""
    async with semaphore:
        service = get_image_gen_service()
        output_path = str(output_dir / f"section_{asset.section_number:02d}.png")

        try:
            logger.info(f"  Generating image for section {asset.section_number}")
            await service.generate_image(
                prompt=asset.prompt,
                output_path=output_path,
            )
            return ImageAsset(
                id=asset.id,
                section_number=asset.section_number,
                prompt=asset.prompt,
                file_path=output_path,
                style=asset.style,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
            )
        except Exception as e:
            logger.error(f"  Failed to generate image for section {asset.section_number}: {e}")
            return asset


async def image_generation_node(state: YouTubePipelineState) -> dict:
    """Generate all images concurrently."""
    logger.info("=== IMAGE GENERATION ===")

    image_assets = state["image_assets"]
    thread_id = state["thread_id"]
    output_dir = Path(settings.youtube_output_dir) / thread_id / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Generating {len(image_assets)} images")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    tasks = [
        _generate_single_image(asset, output_dir, semaphore)
        for asset in image_assets
    ]
    updated_assets = await asyncio.gather(*tasks)

    success_count = sum(1 for a in updated_assets if a.file_path)
    logger.info(f"Generated {success_count}/{len(image_assets)} images")

    warnings = []
    if success_count < len(image_assets):
        warnings.append(f"Failed to generate {len(image_assets) - success_count} images")

    return {
        "image_assets": list(updated_assets),
        "current_phase": "thumbnail_generation",
        "messages": [AIMessage(content=f"Generated {success_count} images")],
        "warnings": warnings,
    }
