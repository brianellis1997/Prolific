"""FastAPI endpoints for the YouTube sleep history pipeline."""

import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prolific.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube", tags=["youtube"])


class GenerateRequest(BaseModel):
    thread_id: str | None = None
    # One of "BIOGRAPHY", "LOST_CIVILIZATION", "IMMERSIVE_DAILY_LIFE".
    # Defaults to BIOGRAPHY for back-compat with existing callers.
    content_mode: str = "BIOGRAPHY"


class ScheduleRequest(BaseModel):
    enabled: bool


_VALID_CONTENT_MODES = {"BIOGRAPHY", "LOST_CIVILIZATION", "IMMERSIVE_DAILY_LIFE"}


def _validate_mode(mode: str) -> str:
    if mode not in _VALID_CONTENT_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid content_mode '{mode}'. Must be one of {sorted(_VALID_CONTENT_MODES)}",
        )
    return mode


@router.post("/generate")
async def generate_video(request: GenerateRequest | None = None):
    """Trigger a YouTube video generation run."""
    from prolific.youtube.graph import run_youtube_pipeline

    thread_id = request.thread_id if request else None
    content_mode = _validate_mode(request.content_mode if request else "BIOGRAPHY")

    try:
        final_state = await run_youtube_pipeline(thread_id=thread_id, content_mode=content_mode)
        return {
            "status": "complete",
            "topic": final_state.get("topic", ""),
            "content_mode": final_state.get("content_mode", content_mode),
            "youtube_url": final_state.get("youtube_url", ""),
            "youtube_video_id": final_state.get("youtube_video_id", ""),
            "word_count": final_state.get("total_script_word_count", 0),
            "errors": final_state.get("errors", []),
        }
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/stream")
async def stream_generate_video(request: GenerateRequest | None = None):
    """Stream a YouTube video generation with SSE progress updates."""
    from prolific.youtube.graph import stream_youtube_pipeline

    thread_id = request.thread_id if request else None
    content_mode = _validate_mode(request.content_mode if request else "BIOGRAPHY")

    async def event_stream():
        async for update in stream_youtube_pipeline(thread_id=thread_id, content_mode=content_mode):
            if "_final_state" in update:
                final = update["_final_state"]
                yield f"data: {json.dumps({'event': 'complete', 'topic': final.get('topic', ''), 'youtube_url': final.get('youtube_url', '')})}\n\n"
            else:
                yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
async def get_video_history(limit: int = 50, content_mode: str | None = None):
    """List past generated videos.

    Optional `?content_mode=BIOGRAPHY|LOST_CIVILIZATION|IMMERSIVE_DAILY_LIFE` filter
    lets analytics dashboards compare per-mode performance.
    """
    from prolific.youtube.services.channel_history import get_channel_history_service

    service = get_channel_history_service()
    await service.initialize()
    if content_mode is not None:
        _validate_mode(content_mode)
        videos = await service.get_videos_by_mode(content_mode=content_mode, limit=limit)
    else:
        videos = await service.get_past_videos(limit=limit)

    return {
        "count": len(videos),
        "content_mode_filter": content_mode,
        "videos": [v.model_dump(mode="json") for v in videos],
    }


@router.post("/schedule")
async def set_schedule(request: ScheduleRequest):
    """Enable or disable the YouTube cron scheduler."""
    from prolific.youtube.scheduler import start_scheduler, stop_scheduler

    if request.enabled:
        start_scheduler()
        return {
            "status": "enabled",
            "schedule": f"{settings.youtube_cron_hour:02d}:{settings.youtube_cron_minute:02d} {settings.youtube_cron_timezone}",
        }
    else:
        stop_scheduler()
        return {"status": "disabled"}


@router.get("/schedule/status")
async def get_schedule_status():
    """Get current scheduler status."""
    return {
        "enabled": settings.youtube_cron_enabled,
        "hour": settings.youtube_cron_hour,
        "minute": settings.youtube_cron_minute,
        "timezone": settings.youtube_cron_timezone,
    }


@router.get("/health")
async def youtube_health():
    """YouTube pipeline health check."""
    import shutil

    has_ffmpeg = shutil.which("ffmpeg") is not None
    has_elevenlabs_key = bool(settings.elevenlabs_api_key)
    has_openrouter_key = bool(settings.openrouter_api_key)

    return {
        "status": "healthy" if all([has_ffmpeg, has_elevenlabs_key, has_openrouter_key]) else "degraded",
        "ffmpeg": has_ffmpeg,
        "elevenlabs_key": has_elevenlabs_key,
        "openrouter_key": has_openrouter_key,
        "youtube_credentials": settings.youtube_credentials_path,
    }
