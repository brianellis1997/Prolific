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

        # "Sleep loop": add this upload to the series playlist so the channel's
        # videos autoplay into one another. Non-fatal — a playlist hiccup must
        # never fail an otherwise-successful upload.
        from prolific.core.config import settings as _settings
        playlist_title = (_settings.youtube_series_playlist_title or "").strip()
        if video_id and playlist_title:
            try:
                playlist_id = await youtube_service.get_or_create_playlist(
                    title=playlist_title,
                    description=(
                        "Long-form sleep documentaries on ancient mysteries and lost "
                        "civilizations. Drift off and let one story flow into the next."
                    ),
                )
                if playlist_id:
                    added = await youtube_service.add_video_to_playlist(playlist_id, video_id)
                    if added:
                        logger.info(f"Added {video_id} to series playlist '{playlist_title}'")
            except Exception as exc:
                logger.warning(f"Playlist add failed (non-fatal): {exc}")

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
        content_mode=state.get("content_mode") or "BIOGRAPHY",
        thumbnail_hook=(thumbnail.title_overlay_text if thumbnail else ""),
    )
    await history_service.record_video(record)

    logger.info(f"Recorded in channel history: {topic}")

    # Persist topic embedding for the dedup gate (only on successful uploads).
    # Failure here must NOT fail the upload — wrap in try/except.
    if video_id:
        try:
            from prolific.core.config import settings
            from prolific.services.topic_dedup import embed_candidate

            vec = await embed_candidate(topic, metadata.title)
            if vec is not None:
                await history_service.update_embedding(video_id, vec, settings.embedding_model)
                logger.info(f"Cached topic embedding for {video_id}")
        except Exception as exc:
            logger.warning(f"Failed to cache topic embedding (non-fatal): {exc}")

    return {
        "youtube_video_id": video_id,
        "youtube_url": video_url,
        "current_phase": "complete",
        "messages": [AIMessage(content=f"Published: {video_url}" if video_url else "Upload failed")],
    }
