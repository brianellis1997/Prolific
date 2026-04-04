"""YouTube upload node - uploads the short to YouTube."""

import logging

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.services.shorts_history import get_shorts_history_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


ENGAGEMENT_COMMENTS = [
    "What do you think about this? Drop your take below",
    "Did you already know about this? Let us know in the comments",
    "This one shocked us. What's your reaction?",
    "We had to share this one. Thoughts?",
    "Tell us what you think below",
]


def _generate_engagement_comment(topic: str) -> str:
    import random
    base = random.choice(ENGAGEMENT_COMMENTS)
    return f"{base} \U0001F447"


async def youtube_upload_node(state: ShortsPipelineState) -> dict:
    """Upload the short to YouTube."""
    logger.info("=== SHORTS: YOUTUBE UPLOAD ===")

    import os
    if os.environ.get("SKIP_YOUTUBE_UPLOAD", "").lower() in ("true", "1", "yes"):
        logger.info("SKIP_YOUTUBE_UPLOAD is set — skipping upload (test mode)")
        return {
            "current_phase": "complete",
            "messages": [AIMessage(content="Upload skipped (test mode)")],
        }

    video_path = state.get("final_video_path", "")
    metadata = state.get("video_metadata")

    if not video_path:
        return {"errors": ["No video to upload"], "current_phase": "failed"}
    if not metadata:
        return {"errors": ["No metadata for upload"], "current_phase": "failed"}

    from prolific.youtube.services.youtube_api import YouTubeUploadService
    upload_service = YouTubeUploadService(credentials_path=settings.shorts_credentials_path)

    try:
        thumbnail_path = state.get("thumbnail_path") or None

        result = await upload_service.upload_video(
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
        logger.info(f"Uploaded to YouTube: {video_url}")

        try:
            comment = _generate_engagement_comment(state.get("topic", ""))
            await upload_service.post_comment(video_id, comment)
        except Exception as e:
            logger.warning(f"Auto-comment failed (non-fatal): {e}")

        history_service = get_shorts_history_service()
        script = state.get("script")

        await history_service.record_short(
            short_id=state["thread_id"],
            topic=state.get("topic", ""),
            hook=script.hook if script else "",
            script_text=script.full_text if script else "",
            word_count=script.word_count if script else 0,
            duration_seconds=state.get("audio_duration_seconds", 0),
            youtube_video_id=video_id,
            youtube_url=video_url,
            video_path=video_path,
            status="published",
        )

        return {
            "youtube_video_id": video_id,
            "youtube_url": video_url,
            "current_phase": "complete",
            "messages": [AIMessage(content=f"Uploaded: {video_url}")],
        }

    except Exception as e:
        logger.error(f"YouTube upload failed: {e}")
        return {
            "errors": [f"Upload failed: {e}"],
            "current_phase": "failed",
            "messages": [AIMessage(content=f"Upload failed: {e}")],
        }
