"""APScheduler-based cron for the shorts pipeline — 4x daily."""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None

SHORTS_SCHEDULE_HOURS = [9, 12, 16, 20]


async def _scheduled_run():
    """Execute a scheduled shorts pipeline run."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"=== SCHEDULED SHORTS RUN TRIGGERED ({now}) ===")
    try:
        from prolific.shorts.graph import run_shorts_pipeline
        state = await run_shorts_pipeline()
        topic = state.get("topic", "?")
        url = state.get("youtube_url", "")
        phase = state.get("current_phase", "?")
        logger.info(f"Scheduled run complete: {topic} | {phase} | {url}")
    except Exception as e:
        logger.error(f"Scheduled shorts run failed: {e}", exc_info=True)


def start_scheduler():
    """Start the shorts scheduler: 4 shorts per day at 9AM, 12PM, 4PM, 8PM ET."""
    global _scheduler

    if not settings.shorts_cron_enabled:
        logger.info("Shorts scheduler disabled (SHORTS_CRON_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = AsyncIOScheduler()

        for hour in SHORTS_SCHEDULE_HOURS:
            trigger = CronTrigger(
                hour=hour,
                minute=0,
                timezone="America/New_York",
            )
            _scheduler.add_job(
                _scheduled_run,
                trigger=trigger,
                id=f"shorts_{hour:02d}",
                name=f"Shorts Pipeline ({hour:02d}:00 ET)",
                replace_existing=True,
            )

        _scheduler.start()
        hours_str = ", ".join(f"{h}:00" for h in SHORTS_SCHEDULE_HOURS)
        logger.info(f"Shorts scheduler started: daily at {hours_str} ET")

    except ImportError:
        logger.warning("APScheduler not installed. Run: pip install apscheduler")
    except Exception as e:
        logger.error(f"Failed to start shorts scheduler: {e}")


def stop_scheduler():
    """Stop the shorts scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Shorts scheduler stopped")
        _scheduler = None
