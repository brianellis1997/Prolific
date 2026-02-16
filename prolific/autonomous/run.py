"""Autonomous blog publishing pipeline.

Discovers trending topics, selects the best one, generates a full
blog post using the Prolific LangGraph pipeline, and publishes it.

Usage:
    PYTHONPATH=. python -m prolific.autonomous.run
"""

import asyncio
import logging
import sys
import traceback as tb
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

    from prolific.services.usage_tracker import reset_usage_tracker, get_usage_tracker
    from prolific.services.cost_calculator import calculate_costs
    from prolific.autonomous.metrics import load_metrics, save_metrics, build_run_record

    reset_usage_tracker()
    project_root = Path(__file__).parent.parent.parent

    selected = None
    final_state = None
    thread_id = None
    result = None
    error_msg = None
    traceback_str = None
    exit_code = 0

    try:
        logger.info("=== STEP 1: TOPIC DISCOVERY ===")
        from prolific.autonomous.topic_discovery import discover_trending_topics
        candidates = await discover_trending_topics(max_candidates=15)
        logger.info(f"Discovered {len(candidates)} topic candidates")

        if not candidates:
            logger.warning("No topic candidates found. Exiting.")
            error_msg = "No topic candidates found"
            exit_code = 1
            return exit_code

        logger.info("=== STEP 2: ANALYZING EXISTING POSTS ===")
        from prolific.autonomous.content_analyzer import get_existing_posts
        existing_posts = get_existing_posts()
        logger.info(f"Found {len(existing_posts)} existing blog posts")

        logger.info("=== STEP 3: TOPIC SELECTION ===")
        from prolific.autonomous.topic_selector import select_topic
        selected = await select_topic(candidates, existing_posts)

        if selected is None:
            logger.info("No suitable topic selected (all duplicates?). Exiting gracefully.")
            exit_code = 0
            return exit_code

        logger.info(f"Selected topic: {selected.topic}")
        logger.info(f"Subtopics: {selected.subtopics}")
        logger.info(f"Rationale: {selected.rationale}")

        logger.info("=== STEP 4: CONTENT GENERATION ===")
        from prolific.agent.graph import run_content_generation
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

        draft_chunks = final_state.get("draft_chunks", [])
        if not draft_chunks:
            error_msg = "No draft chunks produced"
            exit_code = 1
            return exit_code

        total_words = sum(getattr(c, "word_count", 0) for c in draft_chunks)
        logger.info(f"Generated {len(draft_chunks)} chunks, {total_words} words")

        logger.info("=== STEP 5: PUBLISHING ===")
        from prolific.autonomous.publisher import publish_blog_post
        result = await publish_blog_post(
            final_state=final_state,
            topic=selected.topic,
            project_root=project_root,
        )
        if result.status != "published":
            error_msg = result.error
            exit_code = 1
            return exit_code
        logger.info(f"Published: {result.file_path}")
        logger.info(f"Images copied: {result.images_copied}")

        logger.info("=== STEP 5b: PRESENTATION GENERATION ===")
        from prolific.services.pptx_export import generate_presentation
        blog_images_dir = project_root / "blog" / "public" / "images" / result.slug
        try:
            pptx_path = await generate_presentation(
                final_state=final_state,
                slug=result.slug,
                topic=selected.topic,
                project_root=project_root,
                blog_images_dir=blog_images_dir,
            )
            if pptx_path:
                logger.info(f"Presentation saved: {pptx_path}")
            else:
                logger.warning("Presentation generation returned None")
        except Exception as pptx_err:
            logger.warning(f"Presentation generation failed (non-fatal): {pptx_err}")

    except Exception as e:
        error_msg = str(e)
        traceback_str = tb.format_exc()
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        exit_code = 1

    finally:
        end_time = datetime.utcnow()
        usage_summary = get_usage_tracker().get_summary()
        costs = calculate_costs(usage_summary)

        record = build_run_record(
            start_time=start_time,
            end_time=end_time,
            status="success" if error_msg is None else "failed",
            topic=selected.topic if selected else None,
            slug=result.slug if result else None,
            rationale=selected.rationale if selected else None,
            builds_on=selected.builds_on if selected else None,
            final_state=final_state,
            costs=costs,
            thread_id=thread_id,
            error=error_msg,
            traceback=traceback_str,
        )

        metrics = load_metrics(project_root)
        metrics["runs"].append(record)
        save_metrics(project_root, metrics)
        logger.info(f"Metrics saved. Cost: ${costs.get('total_cost_usd', 0):.4f}")

    if exit_code == 0 and result:
        logger.info("=== STEP 6: GIT COMMIT & PUSH ===")
        from prolific.autonomous.publisher import git_commit_and_push
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

    return exit_code


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
