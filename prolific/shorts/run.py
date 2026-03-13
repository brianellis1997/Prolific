"""CLI entry point for the shorts pipeline."""

import asyncio
import logging
import sys

logger = logging.getLogger(__name__)


async def main():
    """Run the shorts pipeline once."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("=== STARTING SHORTS PIPELINE ===")

    from prolific.services.cost_tracker import snapshot_after, snapshot_before

    before = await snapshot_before()

    from prolific.shorts.graph import run_shorts_pipeline

    final_state = await run_shorts_pipeline()

    cost = await snapshot_after(before)
    logger.info(cost.summary)

    topic = final_state.get("topic", "unknown")
    video_path = final_state.get("final_video_path", "")
    youtube_url = final_state.get("youtube_url", "")
    errors = final_state.get("errors", [])
    warnings = final_state.get("warnings", [])

    logger.info("=== SHORTS PIPELINE COMPLETE ===")
    logger.info(f"Topic: {topic}")
    if video_path:
        logger.info(f"Video: {video_path}")
    if youtube_url:
        logger.info(f"YouTube URL: {youtube_url}")
    if warnings:
        logger.warning(f"Warnings: {warnings}")
    if errors:
        logger.warning(f"Errors: {errors}")

    return final_state


if __name__ == "__main__":
    asyncio.run(main())
