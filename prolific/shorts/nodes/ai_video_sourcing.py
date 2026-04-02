"""AI video sourcing node — generates video clips via Kling AI (FAL.ai)."""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def ai_video_sourcing_node(state: ShortsPipelineState) -> dict:
    """Generate AI video clips for assets with type 'ai_video'."""
    logger.info("=== SHORTS: AI VIDEO SOURCING (Kling) ===")

    visual_assets = state.get("visual_assets", [])
    thread_id = state.get("thread_id", "unknown")
    selected_character = state.get("selected_character", "marble")

    pending = [a for a in visual_assets if a.asset_type == "ai_video" and not a.file_path]
    if not pending:
        logger.info("No ai_video assets to generate")
        return {"visual_assets": visual_assets, "current_phase": "tts_generation"}

    logger.info(f"Generating {len(pending)} AI video clips (character={selected_character})")

    from prolific.shorts.services.kling_video import get_kling_service
    kling = get_kling_service()

    output_dir = Path(settings.shorts_output_dir) / thread_id / "ai_clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    semaphore = asyncio.Semaphore(settings.kling_max_concurrent)
    generated = 0
    fallback_count = 0
    total_cost = 0.0

    async def _generate_one(asset):
        nonlocal generated, fallback_count, total_cost
        async with semaphore:
            prompt = asset.video_prompt or asset.search_query
            if not prompt:
                prompt = f"A scene related to: {asset.script_text[:100]}"

            character = asset.character or selected_character
            output_path = str(output_dir / f"ai_clip_{asset.sequence_number:02d}.mp4")

            result = await kling.generate_video(
                prompt=prompt,
                output_path=output_path,
                character=character,
                duration=settings.kling_video_duration,
            )

            if result:
                asset.file_path = result
                asset.width = 1080
                asset.height = 1920
                cost = float(settings.kling_video_duration) * settings.kling_cost_per_sec_usd
                total_cost += cost
                generated += 1
                logger.info(
                    f"[{asset.sequence_number}] AI video: {prompt[:50]}... -> {result}"
                )
            else:
                logger.warning(
                    f"[{asset.sequence_number}] Kling failed, falling back to Pexels: {prompt[:50]}..."
                )
                await _fallback_to_pexels(asset, thread_id)
                fallback_count += 1

    tasks = [_generate_one(a) for a in pending]
    await asyncio.gather(*tasks)

    logger.info(
        f"AI video sourcing complete: {generated}/{len(pending)} generated, "
        f"{fallback_count} fell back to Pexels, total cost: ${total_cost:.2f}"
    )

    return {
        "visual_assets": visual_assets,
        "current_phase": "tts_generation",
        "messages": [AIMessage(
            content=f"AI video: {generated}/{len(pending)} clips generated "
                    f"(${total_cost:.2f}), {fallback_count} Pexels fallbacks"
        )],
    }


async def _fallback_to_pexels(asset, thread_id: str):
    """Fall back to Pexels stock clip when Kling generation fails."""
    try:
        from prolific.shorts.services.pexels import get_pexels_service
        pexels = get_pexels_service()

        output_path = str(
            Path(settings.shorts_output_dir) / thread_id / "clips"
            / f"fallback_{asset.sequence_number:02d}.mp4"
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        query = asset.search_query or asset.video_prompt or "nature scenery"
        result = await pexels.fetch_clip(
            query=query,
            output_path=output_path,
            duration=asset.duration_seconds,
        )

        if result:
            asset.file_path = result
            asset.asset_type = "stock_clip"
            logger.info(f"Pexels fallback success: {query[:40]}... -> {result}")
        else:
            logger.warning(f"Pexels fallback also failed for: {query[:40]}...")
    except Exception as e:
        logger.error(f"Pexels fallback error: {e}")
