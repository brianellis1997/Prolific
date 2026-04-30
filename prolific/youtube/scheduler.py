"""APScheduler cron for YouTube long-form video generation.

Three independent jobs run on a 5-day weekly cadence:
  - Mon/Wed/Fri at youtube_cron_hour ET → BIOGRAPHY mode
  - Thursday at youtube_cron_hour ET → LOST_CIVILIZATION mode
  - Saturday at youtube_cron_hour ET → IMMERSIVE_DAILY_LIFE mode

Each variant mode has its own *_enabled config flag so it can be paused without
disabling the whole pipeline. The shared `slumber_archives_youtube` pipeline_lock
prevents concurrent runs across modes (handled inside graph.run_youtube_pipeline).
"""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


def _make_scheduled_run(mode: str):
    """Build a scheduled-run coroutine bound to a specific content mode.

    Returns a no-arg coroutine APScheduler can invoke. Captures `mode` in closure.
    """
    async def _scheduled_run():
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        logger.info(f"=== SCHEDULED YOUTUBE RUN TRIGGERED ({now}, mode={mode}) ===")
        try:
            from prolific.youtube.run import main
            exit_code = await main(content_mode=mode)
            if exit_code != 0:
                logger.error(f"Scheduled run [{mode}] failed with exit code {exit_code}")
            else:
                logger.info(f"Scheduled YouTube run [{mode}] completed successfully")
        except Exception as e:
            logger.error(f"Scheduled run [{mode}] crashed: {e}", exc_info=True)

    return _scheduled_run


def start_scheduler():
    """Start the YouTube pipeline scheduler with three mode-specific jobs."""
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

    hour = settings.youtube_cron_hour
    minute = settings.youtube_cron_minute
    tz = settings.youtube_cron_timezone

    # Job 1 (always on): BIOGRAPHY on Mon/Wed/Fri — channel baseline.
    _scheduler.add_job(
        _make_scheduled_run("BIOGRAPHY"),
        CronTrigger(day_of_week="mon,wed,fri", hour=hour, minute=minute, timezone=tz),
        id="youtube_mwf_bio",
        name=f"YouTube BIOGRAPHY (Mon/Wed/Fri {hour:02d}:{minute:02d} {tz})",
        replace_existing=True,
    )
    active_jobs = ["youtube_mwf_bio"]

    # Job 2 (gated): LOST_CIVILIZATION on Thursdays.
    if settings.youtube_lostciv_enabled:
        _scheduler.add_job(
            _make_scheduled_run("LOST_CIVILIZATION"),
            CronTrigger(
                day_of_week=settings.youtube_lostciv_cron_day,
                hour=hour, minute=minute, timezone=tz,
            ),
            id="youtube_thu_lostciv",
            name=f"YouTube LOST_CIVILIZATION ({settings.youtube_lostciv_cron_day} {hour:02d}:{minute:02d} {tz})",
            replace_existing=True,
        )
        active_jobs.append("youtube_thu_lostciv")

    # Job 3 (gated): IMMERSIVE_DAILY_LIFE on Saturdays.
    if settings.youtube_immersive_enabled:
        _scheduler.add_job(
            _make_scheduled_run("IMMERSIVE_DAILY_LIFE"),
            CronTrigger(
                day_of_week=settings.youtube_immersive_cron_day,
                hour=hour, minute=minute, timezone=tz,
            ),
            id="youtube_sat_immersive",
            name=f"YouTube IMMERSIVE_DAILY_LIFE ({settings.youtube_immersive_cron_day} {hour:02d}:{minute:02d} {tz})",
            replace_existing=True,
        )
        active_jobs.append("youtube_sat_immersive")

    _scheduler.start()
    logger.info(
        f"YouTube scheduler started with {len(active_jobs)} active jobs: {', '.join(active_jobs)} "
        f"(daily fire time: {hour:02d}:{minute:02d} {tz})"
    )


def stop_scheduler():
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("YouTube scheduler stopped")
