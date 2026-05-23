"""APScheduler-based cron for the shorts pipeline.

Schedule is config-driven (settings.shorts_cron_hours, comma-separated ET hours).
Cut from 4/day to 2/day on 2026-05-20 after the Shorts feed throttle event.
"""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


def _parse_schedule_hours() -> list[int]:
    """Parse SHORTS_CRON_HOURS env var into a list of ints. Falls back to 2/day."""
    raw = (settings.shorts_cron_hours or "").strip()
    if not raw:
        return [12, 20]
    try:
        return [int(h.strip()) for h in raw.split(",") if h.strip()]
    except ValueError:
        logger.warning(f"Could not parse SHORTS_CRON_HOURS={raw!r} — defaulting to 12,20")
        return [12, 20]


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
    """Start the shorts scheduler. Hours come from SHORTS_CRON_HOURS env var."""
    global _scheduler

    if not settings.shorts_cron_enabled:
        logger.info("Shorts scheduler disabled (SHORTS_CRON_ENABLED=false)")
        return

    schedule_hours = _parse_schedule_hours()
    if not schedule_hours:
        logger.warning("No shorts cron hours configured — scheduler not starting")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = AsyncIOScheduler()

        for hour in schedule_hours:
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
        hours_str = ", ".join(f"{h}:00" for h in schedule_hours)
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
