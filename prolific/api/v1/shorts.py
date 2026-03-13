"""FastAPI endpoints for the shorts pipeline."""

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/shorts", tags=["shorts"])
logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    thread_id: str | None = None


class ScheduleRequest(BaseModel):
    enabled: bool


@router.post("/generate")
async def generate_short(request: GenerateRequest | None = None):
    """Trigger a single short generation."""
    from prolific.shorts.graph import run_shorts_pipeline

    thread_id = request.thread_id if request else None
    final_state = await run_shorts_pipeline(thread_id=thread_id)

    return {
        "thread_id": final_state.get("thread_id", ""),
        "topic": final_state.get("topic", ""),
        "youtube_url": final_state.get("youtube_url", ""),
        "errors": final_state.get("errors", []),
    }


@router.post("/generate/stream")
async def generate_short_stream(request: GenerateRequest | None = None):
    """Stream short generation with real-time progress."""
    from prolific.shorts.graph import stream_shorts_pipeline

    thread_id = request.thread_id if request else None

    async def event_stream():
        async for update in stream_shorts_pipeline(thread_id=thread_id):
            if "_final_state" in update:
                final = update["_final_state"]
                yield f"data: {json.dumps({'event': 'complete', 'topic': final.get('topic', ''), 'youtube_url': final.get('youtube_url', '')})}\n\n"
            else:
                yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/history")
async def get_history(limit: int = 50):
    """Get recent shorts history."""
    from prolific.shorts.services.shorts_history import get_shorts_history_service

    service = get_shorts_history_service()
    history = await service.get_history(limit=limit)
    return {"shorts": history, "count": len(history)}


@router.post("/schedule")
async def set_schedule(request: ScheduleRequest):
    """Enable or disable the shorts scheduler."""
    from prolific.shorts.scheduler import start_scheduler, stop_scheduler

    if request.enabled:
        start_scheduler()
        return {"status": "enabled"}
    else:
        stop_scheduler()
        return {"status": "disabled"}


@router.get("/schedule/status")
async def get_schedule_status():
    """Get current scheduler status."""
    from prolific.core.config import settings
    from prolific.shorts.scheduler import _scheduler

    return {
        "enabled": settings.shorts_cron_enabled,
        "interval_hours": settings.shorts_cron_interval_hours,
        "running": _scheduler is not None and _scheduler.running if _scheduler else False,
    }


@router.get("/health")
async def health_check():
    """Health check for shorts pipeline dependencies."""
    import shutil

    from prolific.core.config import settings

    checks = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "elevenlabs_key": bool(settings.elevenlabs_shorts_voice_id or settings.elevenlabs_voice_id),
        "openrouter_key": bool(settings.openrouter_api_key),
        "pexels_key": bool(settings.pexels_api_key),
        "youtube_creds": bool(settings.youtube_credentials_path),
    }

    all_ok = all(checks.values())
    return {"healthy": all_ok, "checks": checks}
