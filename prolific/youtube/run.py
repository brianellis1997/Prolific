"""CLI entry point for the YouTube sleep history pipeline.

Usage:
    PYTHONPATH=. python -m prolific.youtube.run
"""

import asyncio
import logging
import sys
from datetime import datetime, UTC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("youtube_pipeline")


async def main() -> int:
    start_time = datetime.now(UTC)
    logger.info("=== YOUTUBE SLEEP HISTORY PIPELINE STARTING ===")

    exit_code = 0
    from prolific.core.pipeline_lock import acquire_pipeline, release_pipeline
    run_id = acquire_pipeline("slumber_archives_youtube")

    try:
        from prolific.youtube.services.cost_tracker import snapshot_before, snapshot_after

        before = await snapshot_before()
        logger.info(
            f"Pre-run: 11Labs {before['elevenlabs_credits_used']:,}/{before['elevenlabs_credits_limit']:,} credits used "
            f"({before['elevenlabs_tier']}), OpenRouter ${before['openrouter_total_usd']:.4f} total"
        )

        from prolific.youtube.graph import run_youtube_pipeline

        final_state = await run_youtube_pipeline()

        cost = await snapshot_after(before)

        topic = final_state.get("topic", "unknown")
        video_url = final_state.get("youtube_url", "")
        word_count = final_state.get("total_script_word_count", 0)
        errors = final_state.get("errors", [])

        if video_url:
            logger.info(f"Published: {video_url}")
            logger.info(f"Topic: {topic}")
            logger.info(f"Script: {word_count} words")
            logger.info(cost.summary)
        elif errors:
            logger.error(f"Pipeline completed with errors: {errors}")
            logger.info(cost.summary)
            exit_code = 1
        else:
            logger.warning("Pipeline completed but no video URL returned")
            logger.info(cost.summary)
            exit_code = 1

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        exit_code = 1

    release_pipeline(run_id)
    elapsed = (datetime.now(UTC) - start_time).total_seconds()
    logger.info(f"=== PIPELINE {'COMPLETE' if exit_code == 0 else 'FAILED'} in {elapsed:.0f}s ===")

    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
