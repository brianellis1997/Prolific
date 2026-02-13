"""Autonomous blog publishing pipeline.

Discovers trending topics, selects the best one, generates a full
blog post using the Prolific LangGraph pipeline, and publishes it.

Usage:
    PYTHONPATH=. python -m prolific.autonomous.run
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("autonomous")


async def main() -> int:
    start_time = datetime.utcnow()
    logger.info("=== AUTONOMOUS BLOG PIPELINE STARTING ===")

    logger.info("=== STEP 1: TOPIC DISCOVERY ===")
    from prolific.autonomous.topic_discovery import discover_trending_topics

    try:
        candidates = await discover_trending_topics(max_candidates=15)
        logger.info(f"Discovered {len(candidates)} topic candidates")
    except Exception as e:
        logger.error(f"Topic discovery failed: {e}", exc_info=True)
        return 1

    if not candidates:
        logger.warning("No topic candidates found. Exiting.")
        return 1

    logger.info("=== STEP 2: ANALYZING EXISTING POSTS ===")
    from prolific.autonomous.content_analyzer import get_existing_posts

    existing_posts = get_existing_posts()
    logger.info(f"Found {len(existing_posts)} existing blog posts")

    logger.info("=== STEP 3: TOPIC SELECTION ===")
    from prolific.autonomous.topic_selector import select_topic

    try:
        selected = await select_topic(candidates, existing_posts)
    except Exception as e:
        logger.error(f"Topic selection failed: {e}", exc_info=True)
        return 1

    if selected is None:
        logger.info("No suitable topic selected (all duplicates?). Exiting gracefully.")
        return 0

    logger.info(f"Selected topic: {selected.topic}")
    logger.info(f"Subtopics: {selected.subtopics}")
    logger.info(f"Focus areas: {selected.focus_areas}")
    logger.info(f"Rationale: {selected.rationale}")

    logger.info("=== STEP 4: CONTENT GENERATION ===")
    from prolific.agent.graph import run_content_generation

    try:
        final_state, thread_id = await run_content_generation(
            topic=selected.topic,
            subtopics=selected.subtopics,
            focus_areas=selected.focus_areas,
            target_word_count=5000,
            depth="standard",
            style_preferences={
                "tone": selected.style_tone,
                "citation_style": "inline",
            },
            max_iterations=3,
        )
        logger.info(f"Content generation complete. Thread: {thread_id}")
    except Exception as e:
        logger.error(f"Content generation failed: {e}", exc_info=True)
        return 1

    draft_chunks = final_state.get("draft_chunks", [])
    if not draft_chunks:
        logger.error("No draft chunks produced. Pipeline produced empty output.")
        return 1

    total_words = sum(getattr(c, "word_count", 0) for c in draft_chunks)
    logger.info(f"Generated {len(draft_chunks)} chunks, {total_words} words")

    logger.info("=== STEP 5: PUBLISHING ===")
    from prolific.autonomous.publisher import git_commit_and_push, publish_blog_post

    project_root = Path(__file__).parent.parent.parent
    try:
        result = await publish_blog_post(
            final_state=final_state,
            topic=selected.topic,
            project_root=project_root,
        )
        if result.status != "published":
            logger.error(f"Publishing failed: {result.error}")
            return 1
        logger.info(f"Published: {result.file_path}")
        logger.info(f"Images copied: {result.images_copied}")
    except Exception as e:
        logger.error(f"Publishing failed: {e}", exc_info=True)
        return 1

    logger.info("=== STEP 6: GIT COMMIT & PUSH ===")
    git_status = git_commit_and_push(
        file_path=Path(result.file_path),
        images_dir=project_root / "blog" / "public" / "images" / result.slug,
        topic=selected.topic,
        project_root=project_root,
    )
    if git_status.startswith("git_failed"):
        logger.error(f"Git push failed: {git_status}")
        return 1
    logger.info(f"Git status: {git_status}")

    elapsed = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"=== PIPELINE COMPLETE in {elapsed:.0f}s ===")
    logger.info(f"Published: {selected.topic}")
    logger.info(f"URL: /posts/{result.slug}")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
