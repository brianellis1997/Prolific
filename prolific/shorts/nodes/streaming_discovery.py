"""Streaming drama discovery node — finds trending drama via web search, then matches clips.

Step 1: Web search for what's actually trending in streaming drama
Step 2: LLM picks the hottest story from search results
Step 3: Match available Twitch/Kick clips to that story
Step 4: If no clips match, search YouTube for clips about the topic
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


DRAMA_SEARCH_QUERIES = [
    "streaming drama controversy this week twitch kick",
    "streamer beef drama ban exposed today",
    "twitch kick streamer controversy viral clip",
]


class TrendingDrama(BaseModel):
    topic: str = ""
    story_angle: str = ""
    creators_involved: list[str] = Field(default_factory=list)
    clip_search_queries: list[str] = Field(default_factory=list)


TOPIC_SELECTION_PROMPT = """You are a streaming drama content curator. Based on web search results
about current streaming drama, pick the SINGLE hottest story that would make the best YouTube Short.

=== WEB SEARCH RESULTS ===
{search_results}

=== AVAILABLE CLIPS FROM TWITCH/KICK (last 48 hours) ===
{clip_list}

ALREADY COVERED (do NOT pick):
{past_topics}

Pick the story that:
1. Is ACTUALLY trending — people are talking about it on Reddit, Twitter, YouTube
2. Has real DRAMA — beef, bans, exposures, confrontations, meltdowns (not just "popular clip")
3. Multiple clips or angles exist (so we can build a 30-second story)
4. Would make someone stop scrolling and say "wait what?"

Return:
- topic: Punchy headline (e.g., "Clavicular Gets Slapped at Nightclub on Stream")
- story_angle: One-sentence hook with the most shocking detail
- creators_involved: Streamer names in the story
- clip_search_queries: 3-4 YouTube search queries to find clips about THIS specific story
  (e.g., "Clavicular nightclub slap clip", "Clavicular kick stream slap reaction")

If a story from the web search matches clips in the available list, PREFER that story.
The best topic has BOTH web buzz AND available clips."""


CLIP_MATCHING_PROMPT = """Match available Twitch/Kick clips to this specific story.

STORY: {topic}
CREATORS: {creators}
STORY ANGLE: {story_angle}

AVAILABLE CLIPS:
{clip_list}

Select 3-4 clips that relate to this story. Pick clips where:
- The streamer is one of the creators involved (even if the clip title is vague)
- OR the clip title mentions the same event/topic
- OR the clip is from the same streamer during a recent broadcast

Be LENIENT — if a clip is from the right streamer, include it even if the title
doesn't explicitly mention the story. Streamers' recent clips are likely related.

If fewer than 2 clips match, return an empty list — we'll search YouTube instead.

Return only clip URLs from the list above that match. Do NOT fabricate URLs."""


class ClipMatchResult(BaseModel):
    matched_urls: list[str] = Field(default_factory=list)


async def streaming_discovery_node(state: ShortsPipelineState) -> dict:
    """Discover trending streaming drama via web search, then find matching clips."""
    logger.info("=== SHORTS: STREAMING DRAMA DISCOVERY (Twitch + Kick) ===")

    import asyncio
    from prolific.services.web_search import WebSearchService
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

    llm_service = get_llm_service()

    search_service = WebSearchService()
    search_tasks = [
        search_service.search(
            q, max_results=5,
            include_domains=["reddit.com", "dexerto.com", "kotaku.com", "dotesports.com",
                             "ginx.tv", "livestreamfails.com", "twitter.com", "x.com"],
        )
        for q in DRAMA_SEARCH_QUERIES
    ]

    client = get_twitch_client()
    clip_tasks = [
        client.get_top_clips(JUST_CHATTING_GAME_ID, hours_back=48, max_clips=35),
        client.get_top_clips(IRL_GAME_ID, hours_back=48, max_clips=15),
        get_kick_clips(time_range="day", max_clips=30),
    ]

    all_results = await asyncio.gather(*search_tasks, *clip_tasks, return_exceptions=True)

    search_results_raw = []
    for r in all_results[:len(search_tasks)]:
        if isinstance(r, Exception):
            logger.warning(f"Search failed: {r}")
        else:
            search_results_raw.extend(r)

    twitch_jc = all_results[len(search_tasks)] if not isinstance(all_results[len(search_tasks)], Exception) else []
    twitch_irl = all_results[len(search_tasks)+1] if not isinstance(all_results[len(search_tasks)+1], Exception) else []
    kick_clips = all_results[len(search_tasks)+2] if not isinstance(all_results[len(search_tasks)+2], Exception) else []

    for clip in list(twitch_jc) + list(twitch_irl):
        clip["platform"] = "twitch"
    for clip in list(kick_clips):
        clip["platform"] = "kick"

    twitch_all = list(twitch_jc) + list(twitch_irl)
    kick_all = list(kick_clips)
    top_twitch = sorted(twitch_all, key=twitch_score, reverse=True)[:15]
    top_kick = sorted(kick_all, key=kick_score, reverse=True)[:10]
    combined = top_twitch + top_kick

    logger.info(f"Web search: {len(search_results_raw)} results | Clips: {len(twitch_all)} Twitch, {len(kick_all)} Kick")

    search_text_parts = []
    seen_titles = set()
    for r in search_results_raw:
        title = r.title if hasattr(r, 'title') else str(r.get('title', ''))
        if title in seen_titles:
            continue
        seen_titles.add(title)
        snippet = r.snippet if hasattr(r, 'snippet') else str(r.get('snippet', ''))
        search_text_parts.append(f"- {title}\n  {snippet}")
    search_text = "\n".join(search_text_parts[:15]) or "(no search results)"
    logger.info(f"Top search results:\n{search_text[:500]}")

    clip_lines = []
    for i, clip in enumerate(combined):
        views = clip.get("view_count", 0) or 0
        duration = clip.get("duration", 0) or 0
        platform = clip.get("platform", "?").upper()
        broadcaster = clip.get("broadcaster_name", "?")
        clip_lines.append(
            f"[{i+1}][{platform}] \"{clip.get('title', '')}\" | "
            f"Streamer: {broadcaster} | Views: {views:,} | "
            f"Duration: {duration:.0f}s | URL: {clip.get('url', '')}"
        )
    clip_list_str = "\n".join(clip_lines) or "(no clips available)"

    from prolific.shorts.services.shorts_history import get_shorts_history_service
    history_service = get_shorts_history_service()
    past_topics = await history_service.get_past_topics(hours=168)
    past_topics_str = "\n".join(f"- {t}" for t in past_topics[:20]) if past_topics else "(none yet)"
    if past_topics:
        logger.info(f"Avoiding {len(past_topics)} past topics")

    drama = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=TOPIC_SELECTION_PROMPT.format(
                search_results=search_text,
                clip_list=clip_list_str,
                past_topics=past_topics_str,
            )),
            HumanMessage(content="Pick the hottest streaming drama story now."),
        ],
        output_schema=TrendingDrama,
        tier="research",
        temperature=0.3,
    )

    topic = drama.topic or "Streaming Drama"
    logger.info(f"Selected topic: {topic}")
    logger.info(f"Story angle: {drama.story_angle}")
    logger.info(f"Creators: {drama.creators_involved}")
    logger.info(f"Clip search queries: {drama.clip_search_queries}")

    clip_urls = []
    if combined:
        match_result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=CLIP_MATCHING_PROMPT.format(
                    topic=topic,
                    creators=", ".join(drama.creators_involved),
                    story_angle=drama.story_angle,
                    clip_list=clip_list_str,
                )),
                HumanMessage(content="Match clips to this story."),
            ],
            output_schema=ClipMatchResult,
            tier="research",
            temperature=0.1,
        )
        valid_urls = {c.get("url", "") for c in combined}
        clip_urls = [u for u in match_result.matched_urls if u in valid_urls][:4]
        logger.info(f"Matched {len(clip_urls)} clips from Twitch/Kick to story")

    if len(clip_urls) < 2:
        logger.info(f"Not enough platform clips ({len(clip_urls)}), will search YouTube for clips")
        source_urls = clip_urls
        search_queries = drama.clip_search_queries or [f"{topic} clip", f"{' '.join(drama.creators_involved)} stream clip"]
        for q in search_queries[:3]:
            source_urls.append(f"ytsearch:{q}")
        clip_urls = source_urls

    platforms_used = set()
    for url in clip_urls:
        if "kick.com" in url:
            platforms_used.add("Kick")
        elif "twitch.tv" in url:
            platforms_used.add("Twitch")
        elif "ytsearch:" in url:
            platforms_used.add("YouTube")

    platform_label = " + ".join(sorted(platforms_used)) if platforms_used else "Streaming"
    logger.info(f"Final: {topic} | {platform_label} | {len(clip_urls)} clip sources")

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
