"""Stock clip sourcing node - downloads and trims clips from Pexels."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.services.pexels import get_pexels_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def stock_clip_sourcing_node(state: ShortsPipelineState) -> dict:
    """Download and trim stock clips for segments marked as stock_clip."""
    logger.info("=== SHORTS: STOCK CLIP SOURCING ===")

    visual_assets = state.get("visual_assets", [])
    stock_segments = [a for a in visual_assets if a.asset_type == "stock_clip"]

    if not stock_segments:
        logger.info("No stock clips to source")
        return {"current_phase": "tts_generation", "messages": [AIMessage(content="No stock clips needed")]}

    pexels = get_pexels_service()
    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    updated_assets = []
    fallback_to_image = []

    for asset in stock_segments:
        output_path = str(output_dir / f"clip_{asset.sequence_number:02d}.mp4")
        result = await pexels.fetch_clip(
            query=asset.search_query,
            output_path=output_path,
            duration=asset.duration_seconds,
            width=asset.width,
            height=asset.height,
        )

        if result:
            updated = VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="stock_clip",
                search_query=asset.search_query,
                file_path=result,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
            )
            updated_assets.append(updated)
            logger.info(f"[{asset.sequence_number}] Stock clip: {asset.search_query} -> {result}")
        else:
            fallback = VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="ai_image",
                image_prompt=f"Dramatic portrait scene related to: {asset.search_query}. Bold colors, 9:16 vertical composition.",
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
            )
            fallback_to_image.append(fallback)
            logger.warning(f"[{asset.sequence_number}] No stock clip for '{asset.search_query}', falling back to AI image")

    all_updated = updated_assets + fallback_to_image

    logger.info(f"Sourced {len(updated_assets)} stock clips, {len(fallback_to_image)} fell back to AI image")

    return {
        "visual_assets": all_updated,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Sourced {len(updated_assets)} stock clips ({len(fallback_to_image)} fallbacks)")],
    }
