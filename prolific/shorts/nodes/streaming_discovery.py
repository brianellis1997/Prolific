"""Streaming drama discovery node — pulls clips from Twitch and Kick, picks the best story.

Cross-platform beef (e.g., xQc on Twitch vs Adin on Kick) is treated as one story.
The LLM selects 2-4 clips from any combination of platforms.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class StreamingDramaStory(BaseModel):
    topic: str = ""
    clip_urls: list[str] = Field(default_factory=list)
    story_angle: str = ""
    creators_involved: list[str] = Field(default_factory=list)


STREAMING_STORY_PROMPT = """You are a streaming drama content curator for YouTube Shorts.
Here are the top trending clips from Twitch and Kick (last 48 hours):

{clip_list}

ALREADY COVERED (do NOT pick these creators or topics again):
{past_topics}

Your job:
1. Find the single most dramatic, viral story — beef, live bans, meltdowns, exposés,
   callouts, confrontations, or shocking moments
2. IMPORTANT: If the drama involves creators across BOTH platforms (e.g., Creator A on
   Twitch responding to Creator B on Kick), SELECT CLIPS FROM BOTH PLATFORMS to tell
   the complete story. Do not limit yourself to one platform.
3. Select 3-4 clips total that together tell ONE cohesive narrative (MINIMUM 3 clips)
4. Prioritize: high view counts + drama keywords + clips that form a beginning/middle/end
5. SKIP any creator or story that appears in the ALREADY COVERED list above

Return:
- topic: Punchy topic (e.g., "xQc and Adin Ross go to war across Twitch and Kick")
- clip_urls: 3-4 clip URLs — can be from Twitch, Kick, or both (MUST be at least 3)
- story_angle: One-sentence hook starting with the most shocking element
- creators_involved: Names of all streamers in the story

RULES:
- Only return URLs from the list above — do not fabricate
- Prefer clips that are under 60 seconds
- If no clear cross-platform beef exists, pick the best single-platform story
- Do NOT pick a story already in the ALREADY COVERED list"""


async def streaming_discovery_node(state: ShortsPipelineState) -> dict:
    """Discover the top streaming drama story across Twitch and Kick."""
    logger.info("=== SHORTS: STREAMING DRAMA DISCOVERY (Twitch + Kick) ===")

    import asyncio
    from prolific.shorts.services.twitch_api import (
        JUST_CHATTING_GAME_ID,
        IRL_GAME_ID,
        get_twitch_client,
        score_clip_drama as twitch_score,
    )
    from prolific.shorts.services.kick_api import (
        get_trending_clips as get_kick_clips,
        score_clip_drama as kick_score,
    )

    client = get_twitch_client()
    llm_service = get_llm_service()

    twitch_jc, twitch_irl, kick_clips = await asyncio.gather(
        client.get_top_clips(JUST_CHATTING_GAME_ID, hours_back=48, max_clips=35),
        client.get_top_clips(IRL_GAME_ID, hours_back=48, max_clips=15),
        get_kick_clips(time_range="day", max_clips=30),
        return_exceptions=True,
    )

    if isinstance(twitch_jc, Exception):
        logger.warning(f"Twitch JC fetch failed: {twitch_jc}")
        twitch_jc = []
    if isinstance(twitch_irl, Exception):
        logger.warning(f"Twitch IRL fetch failed: {twitch_irl}")
        twitch_irl = []
    if isinstance(kick_clips, Exception):
        logger.warning(f"Kick fetch failed: {kick_clips}")
        kick_clips = []

    for clip in twitch_jc + twitch_irl:
        clip["platform"] = "twitch"
    for clip in kick_clips:
        clip["platform"] = "kick"

    twitch_all = list(twitch_jc) + list(twitch_irl)
    kick_all = list(kick_clips)

    logger.info(
        f"Fetched {len(twitch_all)} Twitch clips, {len(kick_all)} Kick clips"
    )

    if not twitch_all and not kick_all:
        logger.warning("No clips found from any platform, falling back to news_commentary")
        return {
            "content_mode": "news_commentary",
            "topic": "trending news",
            "current_phase": "script_writing",
            "messages": [AIMessage(content="No streaming clips found, using news mode")],
        }

    top_twitch = sorted(twitch_all, key=twitch_score, reverse=True)[:15]
    top_kick = sorted(kick_all, key=kick_score, reverse=True)[:10]
    combined = top_twitch + top_kick

    for clip in top_twitch:
        score = twitch_score(clip)
        logger.info(
            f"  [TWITCH] score={score:.2f} views={clip.get('view_count',0):,} "
            f"streamer={clip.get('broadcaster_name','?')} title={clip.get('title','')[:60]}"
        )
    for clip in top_kick:
        score = kick_score(clip)
        logger.info(
            f"  [KICK]   score={score:.2f} views={clip.get('view_count',0):,} "
            f"streamer={clip.get('broadcaster_name','?')} title={clip.get('title','')[:60]}"
        )

    clip_lines = []
    for i, clip in enumerate(combined):
        views = clip.get("view_count", 0) or 0
        duration = clip.get("duration", 0) or 0
        platform = clip.get("platform", "?").upper()
        broadcaster = clip.get("broadcaster_name", "?")
        clip_lines.append(
            f"[{i+1}][{platform}] \"{clip.get('title', '')}\" | "
            f"Streamer: {broadcaster} | "
            f"Views: {views:,} | "
            f"Duration: {duration:.0f}s | "
            f"URL: {clip.get('url', '')}"
        )

    clip_list_str = "\n".join(clip_lines)

    from prolific.shorts.services.shorts_history import get_shorts_history_service
    history_service = get_shorts_history_service()
    past_topics = await history_service.get_past_topics(hours=168)
    if past_topics:
        past_topics_str = "\n".join(f"- {t}" for t in past_topics[:20])
        logger.info(f"Avoiding {len(past_topics)} past topics: {past_topics[:5]}")
    else:
        past_topics_str = "(none yet)"

    logger.info(f"Sending {len(combined)} clips to LLM for cross-platform story selection")

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=STREAMING_STORY_PROMPT.format(
                clip_list=clip_list_str,
                past_topics=past_topics_str,
            )),
            HumanMessage(content="Select the best drama story now."),
        ],
        output_schema=StreamingDramaStory,
        tier="research",
        temperature=0.3,
    )

    topic = result.topic or (combined[0].get("title", "Streaming Drama") if combined else "Streaming Drama")

    valid_urls = {c.get("url", "") for c in combined}
    clip_urls = [u for u in result.clip_urls if u in valid_urls][:4]

    if not clip_urls:
        clip_urls = [c["url"] for c in combined[:3] if c.get("url")]

    platforms_used = set()
    for url in clip_urls:
        if "kick.com" in url or "clips.kick.com" in url:
            platforms_used.add("Kick")
        elif "twitch.tv" in url or "clips.twitch.tv" in url:
            platforms_used.add("Twitch")

    platform_label = " + ".join(sorted(platforms_used)) if platforms_used else "Streaming"
    logger.info(f"Story: {topic}")
    logger.info(f"Platforms in story: {platform_label} | {len(clip_urls)} clips")

    return {
        "topic": topic,
        "content_mode": "clip_compilation",
        "source_urls": clip_urls,
        "compilation_items": [f"clip_{i+1}" for i in range(len(clip_urls))],
        "current_phase": "clip_sourcing",
        "messages": [
            AIMessage(
                content=f"Streaming story [{platform_label}]: {topic} | {len(clip_urls)} clips"
            )
        ],
    }
