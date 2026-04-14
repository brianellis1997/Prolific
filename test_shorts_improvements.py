"""Test run for shorts pipeline improvements.

Tests: cross-session clip dedup, better search queries, Pixabay fallback, improved sync.
Outputs to shorts_output/test_improvements/ — skips YouTube upload.
"""

import asyncio
import logging
import os

os.environ["SKIP_YOUTUBE_UPLOAD"] = "true"
os.environ["SHORTS_HISTORY_DB_PATH"] = "shorts_history.sqlite"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    from dotenv import load_dotenv
    load_dotenv()

    os.environ["SKIP_YOUTUBE_UPLOAD"] = "true"
    os.environ["SHORTS_HISTORY_DB_PATH"] = "shorts_history.sqlite"

    logger.info("=== TEST RUN: Shorts Pipeline Improvements ===")
    logger.info("Testing: clip dedup, query specificity, Pixabay fallback, sync")

    from prolific.shorts.graph import run_shorts_pipeline

    final_state = await run_shorts_pipeline(
        thread_id="test_improvements",
        niche="curiosity",
    )

    topic = final_state.get("topic", "unknown")
    video_path = final_state.get("final_video_path", "")
    errors = final_state.get("errors", [])

    logger.info("=== TEST RUN COMPLETE ===")
    logger.info(f"Topic: {topic}")
    if video_path:
        logger.info(f"Video saved to: {video_path}")
    if errors:
        logger.error(f"Errors: {errors}")

    return final_state


if __name__ == "__main__":
    asyncio.run(main())
