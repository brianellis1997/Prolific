"""Automated comment reply service — AI-generated replies with channel personas."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from prolific.services.llm import get_llm_service
from prolific.youtube.services.comment_tracker import get_comment_tracker
from prolific.youtube.services.youtube_api import YouTubeUploadService

logger = logging.getLogger(__name__)

SHORTS_PERSONA = """You are the social media manager for "Wait Really?" — a fun facts YouTube Shorts channel.
Reply to this viewer comment in 1-2 SHORT sentences. Be energetic, curious, and friendly.
Use the video title for context about what the video was about.
If they share an additional fact, react with genuine excitement.
If they ask a question, answer it briefly if you know, or say something like "great question, we should make a video about that!"
Never be defensive. Keep it casual and fun. No emojis. No hashtags."""

SLUMBER_PERSONA = """You are the narrator behind "The Slumber Archives" — a calm sleep history YouTube channel.
Reply to this viewer comment in 1-2 SHORT sentences. Be warm, gentle, and thoughtful.
Thank them for listening when appropriate. If they mention falling asleep, take it as the highest compliment.
If they share historical knowledge, acknowledge it graciously.
Keep the same calm, wise tone as the narration. No emojis. No hashtags."""

MIN_COMMENT_WORDS = 3
MAX_REPLIES_PER_RUN = 20


async def process_channel_comments(
    channel: str,
    credentials_path: str,
    max_videos: int = 15,
) -> int:
    """Check recent videos for new comments and reply. Returns number of replies posted."""
    logger.info(f"=== COMMENT REPLY CHECK: {channel} ===")

    service = YouTubeUploadService(credentials_path=credentials_path)
    tracker = get_comment_tracker()
    llm_service = get_llm_service()

    our_channel_id = await service.get_channel_id()
    if not our_channel_id:
        logger.warning(f"Could not get channel ID for {channel}, skipping")
        return 0

    video_ids = await service.get_recent_video_ids(max_results=max_videos)
    if not video_ids:
        logger.info(f"No videos found for {channel}")
        return 0

    persona = SLUMBER_PERSONA if channel == "slumber" else SHORTS_PERSONA
    replies_posted = 0

    for video_id in video_ids:
        if replies_posted >= MAX_REPLIES_PER_RUN:
            logger.info(f"Hit max replies ({MAX_REPLIES_PER_RUN}), stopping")
            break

        threads = await service.list_comment_threads(video_id)
        if not threads:
            continue

        video_title = ""
        for thread in threads:
            if replies_posted >= MAX_REPLIES_PER_RUN:
                break

            comment_id = thread["comment_id"]
            author = thread["author"]
            text = thread["text"]
            author_channel_id = thread["author_channel_id"]

            if author_channel_id == our_channel_id:
                continue

            if len(text.split()) < MIN_COMMENT_WORDS:
                continue

            already_replied = await tracker.has_replied(comment_id)
            if already_replied:
                continue

            we_already_replied_on_thread = any(
                r["author_channel_id"] == our_channel_id
                for r in thread.get("existing_replies", [])
            )
            if we_already_replied_on_thread:
                await tracker.record_reply(
                    comment_id, video_id, channel, author, text, "(already replied on thread)"
                )
                continue

            try:
                reply_text = await _generate_reply(
                    llm_service, persona, text, video_title or video_id, author,
                )

                result = await service.reply_to_comment(comment_id, reply_text)
                if result:
                    await tracker.record_reply(
                        comment_id, video_id, channel, author, text, reply_text,
                    )
                    replies_posted += 1
                    logger.info(
                        f"  [{channel}] Replied to {author}: \"{text[:40]}\" -> \"{reply_text[:40]}\""
                    )
            except Exception as e:
                logger.warning(f"  Failed to reply to comment {comment_id}: {e}")

    logger.info(f"Comment reply check complete: {channel} — {replies_posted} replies posted")
    return replies_posted


async def _generate_reply(
    llm_service,
    persona: str,
    comment_text: str,
    video_context: str,
    author_name: str,
) -> str:
    """Generate an AI reply to a comment."""
    response = await llm_service.invoke(
        messages=[
            SystemMessage(content=persona),
            HumanMessage(content=(
                f"Video: {video_context}\n"
                f"Comment by {author_name}: \"{comment_text}\"\n\n"
                f"Write your reply:"
            )),
        ],
        tier="research",
        temperature=0.7,
    )
    reply = response.content.strip().strip('"').strip("'")
    if len(reply) > 500:
        reply = reply[:497] + "..."
    return reply
