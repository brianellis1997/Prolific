"""APScheduler cron setup for daily YouTube video generation."""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


def start_scheduler():
    """Start the YouTube pipeline scheduler if enabled."""
    global _scheduler

    if not settings.youtube_cron_enabled:
        logger.info("YouTube cron disabled (set YOUTUBE_CRON_ENABLED=true to enable)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.warning("APScheduler not installed. Run: pip install apscheduler")
        return

    _scheduler = AsyncIOScheduler()

    trigger = CronTrigger(
        hour=settings.youtube_cron_hour,
        minute=settings.youtube_cron_minute,
        timezone=settings.youtube_cron_timezone,
    )

    _scheduler.add_job(
        _scheduled_run,
        trigger,
        id="youtube_daily",
        name="Daily YouTube Video Generation",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"YouTube scheduler started: daily at "
        f"{settings.youtube_cron_hour:02d}:{settings.youtube_cron_minute:02d} "
        f"{settings.youtube_cron_timezone}"
    )


async def _scheduled_run():
    """Scheduled execution of the YouTube pipeline."""
    logger.info("=== SCHEDULED YOUTUBE RUN TRIGGERED ===")
    try:
        from prolific.youtube.run import main
        exit_code = await main()
        if exit_code != 0:
            logger.error(f"Scheduled run failed with exit code {exit_code}")
    except Exception as e:
        logger.error(f"Scheduled run crashed: {e}", exc_info=True)


def stop_scheduler():
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("YouTube scheduler stopped")
