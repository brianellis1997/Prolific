"""Topic selection node - picks a history topic avoiding past videos."""

import asyncio
import base64
import json
import logging
import os
import random
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.services.channel_history import get_channel_history_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def _get_past_youtube_titles() -> list[str]:
    """Fetch past video titles from the Slumber Archives YouTube channel."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = None
        b64 = os.environ.get("YOUTUBE_CREDENTIALS_B64")
        if b64:
            creds_data = json.loads(base64.b64decode(b64))
        elif Path(settings.youtube_credentials_path).exists():
            creds_data = json.loads(Path(settings.youtube_credentials_path).read_text())

        if not creds_data:
            return []

        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )

        def _fetch():
            yt = build("youtube", "v3", credentials=creds)
            resp = yt.search().list(
                part="snippet", forMine=True, type="video",
                maxResults=50, order="date",
            ).execute()
            return [item["snippet"]["title"] for item in resp.get("items", [])]

        titles = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        logger.info(f"Fetched {len(titles)} past video titles from YouTube")
        return titles

    except Exception as e:
        logger.warning(f"YouTube past titles fetch failed: {e}")
        return []


class TopicCandidate(BaseModel):
    topic: str
    is_biography: bool
    era_tags: list[str] = Field(default_factory=list)
    region_tags: list[str] = Field(default_factory=list)
    appeal_reason: str = ""
    trending_tie_in: str = ""


class TopicBrainstormResult(BaseModel):
    candidates: list[TopicCandidate]


class TopicSelectionResult(BaseModel):
    chosen_index: int
    rationale: str


async def _get_performance_context() -> str:
    """Pull channel analytics to identify what topics/eras/regions perform best."""
    try:
        from prolific.youtube.services.youtube_analytics import get_youtube_analytics_service
        analytics = get_youtube_analytics_service()
        insights = await analytics.get_channel_insights()
        if insights.summary and insights.total_videos_analyzed > 0:
            logger.info(f"Analytics: {insights.total_videos_analyzed} videos analyzed for performance context")
            return insights.summary
        return ""
    except Exception as e:
        logger.warning(f"Analytics fetch failed (non-fatal): {e}")
        return ""


async def _get_trending_context() -> str:
    """Search for trending news and extract historically relevant themes."""
    try:
        from prolific.services.web_search import get_web_search_service
        search_service = get_web_search_service()

        results = await search_service.search(
            query="major world news today trending stories",
            max_results=8,
            search_depth="basic",
        )

        if not results:
            return ""

        headlines = [f"- {r.title}: {r.snippet[:150]}" for r in results[:8]]
        trending_summary = "\n".join(headlines)

        logger.info(f"Fetched {len(headlines)} trending headlines for topic inspiration")
        return trending_summary

    except Exception as e:
        logger.warning(f"Trending news fetch failed (non-fatal): {e}")
        return ""


async def topic_selection_node(state: YouTubePipelineState) -> dict:
    """Select an interesting history topic for the video."""
    logger.info("=== TOPIC SELECTION ===")

    llm_service = get_llm_service()
    history_service = get_channel_history_service()
    await history_service.initialize()

    db_topics = await history_service.get_past_topics(limit=200)
    yt_topics = await _get_past_youtube_titles()
    all_past = list(dict.fromkeys(db_topics + yt_topics))
    past_topics = all_past[:50]
    past_topics_str = "\n".join(f"- {t}" for t in past_topics) if past_topics else "(none yet)"

    total_videos = await history_service.get_total_count()
    bio_count = await history_service.get_biography_count()
    bio_ratio = bio_count / max(total_videos, 1)
    target_ratio = settings.youtube_biography_ratio

    if bio_ratio < target_ratio:
        content_type_instruction = (
            "This video MUST be a BIOGRAPHY / character deep dive. "
            "The channel needs more biography content. Focus on a specific historical figure."
        )
    else:
        use_biography = random.random() < target_ratio
        if use_biography:
            content_type_instruction = (
                "This video should be a BIOGRAPHY / character deep dive about a specific historical figure."
            )
        else:
            content_type_instruction = (
                "This video should be a BROAD TOPIC exploration (civilization, era, event, cultural movement) "
                "rather than a single person's biography."
            )

    trending_context = await _get_trending_context()
    performance_context = await _get_performance_context()

    from prolific.youtube.prompts import TOPIC_BRAINSTORM_SYSTEM

    brainstorm_prompt = TOPIC_BRAINSTORM_SYSTEM.format(
        num_candidates=10,
        content_type_instruction=content_type_instruction,
        past_topics=past_topics_str,
        trending_context=trending_context if trending_context else "(no trending data available)",
        performance_context=performance_context if performance_context else "(no performance data yet - channel is new)",
    )

    brainstorm_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=brainstorm_prompt),
            HumanMessage(content="Generate topic candidates now."),
        ],
        output_schema=TopicBrainstormResult,
        tier="research",
        temperature=0.9,
    )

    candidates = brainstorm_result.candidates
    logger.info(f"Brainstormed {len(candidates)} topic candidates")

    if not candidates:
        return {
            "errors": ["No topic candidates generated"],
            "current_phase": "failed",
        }

    from prolific.youtube.prompts import TOPIC_SELECT_SYSTEM

    candidates_str = "\n".join(
        f"[{i}] {c.topic} (biography={c.is_biography}) - {c.appeal_reason}"
        + (f" [TRENDING: {c.trending_tie_in}]" if c.trending_tie_in else "")
        for i, c in enumerate(candidates)
    )

    selection_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=TOPIC_SELECT_SYSTEM),
            HumanMessage(content=f"Candidates:\n{candidates_str}\n\nSelect the best one."),
        ],
        output_schema=TopicSelectionResult,
        tier="research",
        temperature=0.3,
    )

    chosen_idx = max(0, min(selection_result.chosen_index, len(candidates) - 1))
    chosen = candidates[chosen_idx]

    logger.info(f"Selected topic: {chosen.topic}")
    logger.info(f"Is biography: {chosen.is_biography}")
    logger.info(f"Rationale: {selection_result.rationale}")
    if chosen.trending_tie_in:
        logger.info(f"Trending tie-in: {chosen.trending_tie_in}")

    return {
        "topic": chosen.topic,
        "is_biography": chosen.is_biography,
        "era_tags": chosen.era_tags,
        "region_tags": chosen.region_tags,
        "past_video_topics": past_topics,
        "current_phase": "script_planning",
        "messages": [AIMessage(content=f"Selected topic: {chosen.topic}")],
    }
