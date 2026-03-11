"""CLI entry point for the YouTube sleep history pipeline.

Usage:
    PYTHONPATH=. python -m prolific.youtube.run
"""

import asyncio
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("youtube_pipeline")


async def main() -> int:
    start_time = datetime.utcnow()
    logger.info("=== YOUTUBE SLEEP HISTORY PIPELINE STARTING ===")

    exit_code = 0

    try:
        from prolific.youtube.graph import run_youtube_pipeline

        final_state = await run_youtube_pipeline()

        topic = final_state.get("topic", "unknown")
        video_url = final_state.get("youtube_url", "")
        word_count = final_state.get("total_script_word_count", 0)
        errors = final_state.get("errors", [])

        audio_chunks = final_state.get("audio_chunks", [])
        image_assets = final_state.get("image_assets", [])
        num_images = sum(1 for a in image_assets if a.file_path)
        tts_chars = sum(
            s.word_count * 5.5
            for s in final_state.get("script_sections", [])
        )

        llm_cost = word_count * 0.000015 + 0.20
        image_cost = num_images * 0.15
        tts_cost = tts_chars / 1000 * 0.10
        total_cost = llm_cost + image_cost + tts_cost

        if video_url:
            logger.info(f"Published: {video_url}")
            logger.info(f"Topic: {topic}")
            logger.info(f"Script: {word_count} words")
            logger.info(f"--- COST ESTIMATE ---")
            logger.info(f"  LLM calls: ${llm_cost:.2f}")
            logger.info(f"  Image gen ({num_images} images): ${image_cost:.2f}")
            logger.info(f"  TTS ({tts_chars:.0f} chars): ${tts_cost:.2f}")
            logger.info(f"  TOTAL: ${total_cost:.2f}")
        elif errors:
            logger.error(f"Pipeline completed with errors: {errors}")
            exit_code = 1
        else:
            logger.warning("Pipeline completed but no video URL returned")
            exit_code = 1

    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        exit_code = 1

    elapsed = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"=== PIPELINE {'COMPLETE' if exit_code == 0 else 'FAILED'} in {elapsed:.0f}s ===")

    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
