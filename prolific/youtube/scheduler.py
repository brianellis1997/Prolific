"""APScheduler cron for YouTube long-form video generation — Mon/Wed/Fri 8PM ET."""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


async def _scheduled_run():
    """Scheduled execution of the YouTube pipeline."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"=== SCHEDULED YOUTUBE RUN TRIGGERED ({now}) ===")
    try:
        from prolific.youtube.run import main
        exit_code = await main()
        if exit_code != 0:
            logger.error(f"Scheduled run failed with exit code {exit_code}")
        else:
            logger.info("Scheduled YouTube run completed successfully")
    except Exception as e:
        logger.error(f"Scheduled run crashed: {e}", exc_info=True)


def start_scheduler():
    """Start the YouTube pipeline scheduler: Mon/Wed/Fri at 8PM ET."""
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
        day_of_week="mon,wed,fri",
        hour=settings.youtube_cron_hour,
        minute=settings.youtube_cron_minute,
        timezone=settings.youtube_cron_timezone,
    )

    _scheduler.add_job(
        _scheduled_run,
        trigger,
        id="youtube_mwf",
        name="YouTube Long-Form (Mon/Wed/Fri 8PM ET)",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        f"YouTube scheduler started: Mon/Wed/Fri at "
        f"{settings.youtube_cron_hour:02d}:{settings.youtube_cron_minute:02d} "
        f"{settings.youtube_cron_timezone}"
    )


def stop_scheduler():
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("YouTube scheduler stopped")
