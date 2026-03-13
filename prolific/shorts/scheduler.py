"""APScheduler-based cron for the shorts pipeline."""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


async def _scheduled_run():
    """Execute a scheduled shorts pipeline run."""
    logger.info("=== SCHEDULED SHORTS RUN TRIGGERED ===")
    try:
        from prolific.shorts.run import main
        await main()
    except Exception as e:
        logger.error(f"Scheduled shorts run failed: {e}", exc_info=True)


def start_scheduler():
    """Start the shorts scheduler if enabled."""
    global _scheduler

    if not settings.shorts_cron_enabled:
        logger.info("Shorts scheduler disabled (SHORTS_CRON_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = AsyncIOScheduler()
        trigger = IntervalTrigger(hours=settings.shorts_cron_interval_hours)

        _scheduler.add_job(
            _scheduled_run,
            trigger=trigger,
            id="shorts_pipeline",
            name="Shorts Pipeline",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info(f"Shorts scheduler started: every {settings.shorts_cron_interval_hours} hours")

    except Exception as e:
        logger.error(f"Failed to start shorts scheduler: {e}")


def stop_scheduler():
    """Stop the shorts scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Shorts scheduler stopped")
        _scheduler = None
