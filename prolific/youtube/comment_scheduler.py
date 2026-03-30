"""APScheduler cron for automated comment replies — every 2 hours."""

import logging

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


async def _scheduled_comment_check():
    """Check both channels for new comments and reply."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    logger.info(f"=== SCHEDULED COMMENT REPLY CHECK ({now}) ===")

    try:
        from prolific.youtube.services.comment_replier import process_channel_comments

        shorts_replies = await process_channel_comments(
            "shorts", settings.shorts_credentials_path,
        )
        slumber_replies = await process_channel_comments(
            "slumber", settings.youtube_credentials_path,
        )
        logger.info(
            f"Comment check complete: {shorts_replies} shorts replies, "
            f"{slumber_replies} slumber replies"
        )
    except Exception as e:
        logger.error(f"Comment reply check failed: {e}", exc_info=True)


def start_scheduler():
    """Start the comment reply scheduler if enabled."""
    global _scheduler

    if not settings.comment_reply_enabled:
        logger.info("Comment reply scheduler disabled (COMMENT_REPLY_ENABLED=false)")
        return

    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = AsyncIOScheduler()

        trigger = IntervalTrigger(
            hours=settings.comment_reply_interval_hours,
            minutes=15,
        )

        _scheduler.add_job(
            _scheduled_comment_check,
            trigger=trigger,
            id="comment_reply",
            name=f"Comment Replies (every {settings.comment_reply_interval_hours}h)",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info(
            f"Comment reply scheduler started: every {settings.comment_reply_interval_hours} hours"
        )

    except ImportError:
        logger.warning("APScheduler not installed")
    except Exception as e:
        logger.error(f"Failed to start comment reply scheduler: {e}")


def stop_scheduler():
    """Stop the comment reply scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Comment reply scheduler stopped")
        _scheduler = None
