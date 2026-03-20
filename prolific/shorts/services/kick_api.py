"""Kick API client for fetching trending clips.

Uses curl_cffi for Cloudflare bypass (plain httpx gets blocked).
Correct endpoint: GET /api/v2/clips?sort=view&time=24h
"""

import logging
import math

from prolific.shorts.services.twitch_api import DRAMA_KEYWORDS

logger = logging.getLogger(__name__)

KICK_CLIPS_URL = "https://kick.com/api/v2/clips"

KICK_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://kick.com/clips",
}


async def get_trending_clips(
    time_range: str = "24h",
    max_clips: int = 40,
) -> list[dict]:
    """Fetch trending Kick clips using curl_cffi to bypass Cloudflare.

    time_range: '24h', '7d', '30d', 'all'
    """
    try:
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(impersonate="chrome124") as session:
            resp = await session.get(
                KICK_CLIPS_URL,
                headers=KICK_HEADERS,
                params={
                    "sort": "view",
                    "time": time_range,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            clips_raw = (
                data if isinstance(data, list)
                else data.get("clips", data.get("data", []))
            )
            clips = _normalize_clips(clips_raw[:max_clips])
            logger.info(f"Fetched {len(clips)} Kick clips (time={time_range})")
            return clips

    except Exception as e:
        logger.warning(f"Kick clip fetch failed: {e}")
        return []


def _normalize_clips(raw: list) -> list[dict]:
    """Normalize Kick clip objects to a common shape."""
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            continue

        clip_id = item.get("id") or item.get("slug") or ""
        clip_url = (
            item.get("clip_url")
            or item.get("video_url")
            or item.get("url")
            or (f"https://kick.com/clip/{clip_id}" if clip_id else "")
        )
        if not clip_url:
            continue

        channel = item.get("channel") or {}
        broadcaster_name = (
            channel.get("username")
            or channel.get("slug")
            or item.get("channel_name")
            or "unknown"
        )

        category = item.get("category") or {}
        category_name = category.get("name") or item.get("category_name") or ""

        normalized.append({
            "id": clip_id,
            "url": clip_url,
            "title": item.get("title") or item.get("clip_title") or "",
            "broadcaster_name": broadcaster_name,
            "category_name": category_name,
            "view_count": item.get("view_count") or item.get("views") or 0,
            "duration": item.get("duration") or 0,
            "platform": "kick",
        })

    return normalized


def score_clip_drama(clip: dict) -> float:
    """Score a Kick clip 0-10 for drama potential."""
    title = (clip.get("title") or "").lower()
    views = clip.get("view_count", 0) or 0

    view_score = math.log10(max(views, 1)) / 7 * 5
    keyword_hits = sum(1 for kw in DRAMA_KEYWORDS if kw in title)
    keyword_score = min(keyword_hits * 0.4, 3.0)

    return view_score + keyword_score
