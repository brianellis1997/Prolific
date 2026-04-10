"""YouTube upload node - uploads video and records to channel history."""

import logging
from datetime import datetime

from langchain_core.messages import AIMessage

from prolific.youtube.schemas import VideoRecord
from prolific.youtube.services.channel_history import get_channel_history_service
from prolific.youtube.services.youtube_api import get_youtube_upload_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def youtube_upload_node(state: YouTubePipelineState) -> dict:
    """Upload video to YouTube and record in channel history."""
    logger.info("=== YOUTUBE UPLOAD ===")

    video_path = state["final_video_path"]
    metadata = state["video_metadata"]
    thumbnail = state.get("thumbnail")
    topic = state["topic"]

    if not video_path:
        return {
            "errors": ["No video file to upload"],
            "current_phase": "failed",
        }

    if not metadata:
        return {
            "errors": ["No video metadata generated"],
            "current_phase": "failed",
        }

    youtube_service = get_youtube_upload_service()
    thumbnail_path = thumbnail.file_path if thumbnail else None

    try:
        result = await youtube_service.upload_video(
            video_path=video_path,
            title=metadata.title,
            description=metadata.description,
            tags=metadata.tags,
            category_id=metadata.category_id,
            privacy_status=metadata.privacy_status,
            thumbnail_path=thumbnail_path,
        )

        video_id = result["video_id"]
        video_url = result["url"]
        logger.info(f"Uploaded: {video_url}")

    except Exception as e:
        logger.error(f"Upload failed: {e}")
        video_id = ""
        video_url = ""

    history_service = get_channel_history_service()
    await history_service.initialize()

    total_words = state.get("total_script_word_count", 0)
    audio_chunks = state.get("audio_chunks", [])
    total_duration = sum(c.duration_seconds for c in audio_chunks)

    record = VideoRecord(
        topic=topic,
        title=metadata.title,
        description=metadata.description,
        tags=metadata.tags,
        youtube_video_id=video_id,
        youtube_url=video_url,
        thumbnail_path=thumbnail_path,
        video_path=video_path,
        script_word_count=total_words,
        estimated_duration_minutes=total_duration / 60,
        status="published" if video_id else "failed",
        published_at=datetime.utcnow() if video_id else None,
        era_tags=state.get("era_tags", []),
        region_tags=state.get("region_tags", []),
        is_biography=state.get("is_biography", False),
        selection_rationale=state.get("selection_rationale", ""),
    )
    await history_service.record_video(record)

    logger.info(f"Recorded in channel history: {topic}")

    return {
        "youtube_video_id": video_id,
        "youtube_url": video_url,
        "current_phase": "complete",
        "messages": [AIMessage(content=f"Published: {video_url}" if video_url else "Upload failed")],
    }
