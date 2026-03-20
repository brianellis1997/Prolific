"""Twitch drama discovery node - finds trending Twitch drama clips and forms a story."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class TwitchDramaStory(BaseModel):
    topic: str = ""
    clip_urls: list[str] = Field(default_factory=list)
    story_angle: str = ""
    broadcaster_names: list[str] = Field(default_factory=list)


TWITCH_STORY_PROMPT = """You are a Twitch drama content curator for YouTube Shorts.
Here are the top trending Twitch clips from the last 48 hours:

{clip_list}

Your job:
1. Find the single most dramatic, viral story — beef between streamers, live bans, meltdowns,
   exposés, controversies, callouts, or shocking moments
2. Select 2-4 clips that tell ONE cohesive story (prefer clips from the same incident or streamer)
3. Prioritize: high view counts + drama keywords in title + clips that together form a narrative

Return:
- topic: A punchy topic string (e.g., "xQc calls out Destiny live then gets banned mid-stream")
- clip_urls: 2-4 clip URLs for this story — pick the most dramatic and relevant
- story_angle: One-sentence hook angle for the short (start with the most shocking element)
- broadcaster_names: Names of the streamers involved

IMPORTANT: Only return clip URLs that appear in the list above. Do not fabricate URLs."""


async def twitch_discovery_node(state: ShortsPipelineState) -> dict:
    """Discover the top Twitch drama story and select clips for the short."""
    logger.info("=== SHORTS: TWITCH DRAMA DISCOVERY ===")

    from prolific.shorts.services.twitch_api import (
        JUST_CHATTING_GAME_ID,
        IRL_GAME_ID,
        get_twitch_client,
        score_clip_drama,
    )
    import asyncio

    client = get_twitch_client()
    llm_service = get_llm_service()

    try:
        jc_clips, irl_clips = await asyncio.gather(
            client.get_top_clips(JUST_CHATTING_GAME_ID, hours_back=48, max_clips=40),
            client.get_top_clips(IRL_GAME_ID, hours_back=48, max_clips=20),
            return_exceptions=True,
        )
        if isinstance(jc_clips, Exception):
            logger.warning(f"Just Chatting fetch failed: {jc_clips}")
            jc_clips = []
        if isinstance(irl_clips, Exception):
            logger.warning(f"IRL fetch failed: {irl_clips}")
            irl_clips = []
    except Exception as e:
        logger.error(f"Twitch API fetch failed: {e}")
        return {
            "errors": [f"Twitch API failed: {e}"],
            "content_mode": "news_commentary",
            "current_phase": "script_writing",
            "messages": [AIMessage(content="Twitch fetch failed, falling back to news mode")],
        }

    all_clips = list(jc_clips) + list(irl_clips)
    logger.info(f"Fetched {len(all_clips)} clips total (JC={len(jc_clips)}, IRL={len(irl_clips)})")

    if not all_clips:
        logger.warning("No Twitch clips found, falling back to news_commentary")
        return {
            "content_mode": "news_commentary",
            "topic": "trending news",
            "current_phase": "script_writing",
            "messages": [AIMessage(content="No Twitch clips found, using news mode")],
        }

    scored = sorted(all_clips, key=score_clip_drama, reverse=True)
    top_clips = scored[:25]

    clip_lines = []
    for i, clip in enumerate(top_clips):
        views = clip.get("view_count", 0) or 0
        duration = clip.get("duration", 0) or 0
        clip_lines.append(
            f"[{i+1}] \"{clip.get('title', '')}\" | "
            f"Streamer: {clip.get('broadcaster_name', '?')} | "
            f"Views: {views:,} | "
            f"Duration: {duration:.0f}s | "
            f"URL: {clip.get('url', '')}"
        )

    clip_list_str = "\n".join(clip_lines)
    logger.info(f"Sending top {len(top_clips)} clips to LLM for story selection")

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=TWITCH_STORY_PROMPT.format(clip_list=clip_list_str)),
            HumanMessage(content="Select the best drama story and clips now."),
        ],
        output_schema=TwitchDramaStory,
        tier="research",
        temperature=0.3,
    )

    topic = result.topic or (
        top_clips[0].get("title", "Twitch Drama") if top_clips else "Twitch Drama"
    )

    valid_clip_urls_set = {c.get("url", "") for c in top_clips}
    clip_urls = [u for u in result.clip_urls if u in valid_clip_urls_set][:4]

    if not clip_urls:
        clip_urls = [c["url"] for c in top_clips[:3] if c.get("url")]

    logger.info(f"Selected story: {topic}")
    logger.info(f"Clip URLs ({len(clip_urls)}): {clip_urls}")

    return {
        "topic": topic,
        "content_mode": "clip_compilation",
        "source_urls": clip_urls,
        "compilation_items": [f"clip_{i+1}" for i in range(len(clip_urls))],
        "current_phase": "clip_sourcing",
        "messages": [
            AIMessage(content=f"Twitch story: {topic} | {len(clip_urls)} clips selected")
        ],
    }
