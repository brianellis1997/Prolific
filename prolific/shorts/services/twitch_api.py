"""Twitch API client for fetching trending drama clips."""

import logging
import math
from datetime import datetime, timedelta, timezone

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)

JUST_CHATTING_GAME_ID = "509658"
IRL_GAME_ID = "498566"

DRAMA_KEYWORDS = [
    "banned", "ban", "drama", "beef", "exposed", "confrontation",
    "fight", "rage", "called out", "suspended", "controversy",
    "cheating", "vs", "responds", "destroys", "roasts", "meltdown",
    "freaks out", "cries", "breaks down", "canceled", "scam",
    "racist", "harassment", "leaked", "caught", "claps back",
]


class TwitchApiClient:
    def __init__(self):
        self.client_id = settings.twitch_client_id
        self.client_secret = settings.twitch_client_secret
        self._access_token: str | None = None
        self._token_expires: datetime | None = None

    async def _get_token(self) -> str:
        if (
            self._access_token
            and self._token_expires
            and datetime.now(timezone.utc) < self._token_expires
        ):
            return self._access_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "client_credentials",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires = datetime.now(timezone.utc) + timedelta(
                seconds=expires_in - 300
            )
            logger.info("Twitch app token obtained")
            return self._access_token

    def _headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Client-Id": self.client_id,
        }

    async def get_top_clips(
        self,
        game_id: str,
        hours_back: int = 48,
        max_clips: int = 40,
    ) -> list[dict]:
        """Get top clips for a game in the last N hours."""
        token = await self._get_token()
        started_at = (
            datetime.now(timezone.utc) - timedelta(hours=hours_back)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.twitch.tv/helix/clips",
                headers=self._headers(token),
                params={
                    "game_id": game_id,
                    "first": min(max_clips, 100),
                    "started_at": started_at,
                },
                timeout=15,
            )
            resp.raise_for_status()
            clips = resp.json().get("data", [])
            logger.info(f"Fetched {len(clips)} clips for game_id={game_id}")
            return clips

    async def get_broadcaster_clips(
        self,
        broadcaster_id: str,
        hours_back: int = 48,
        max_clips: int = 10,
    ) -> list[dict]:
        """Get recent clips from a specific broadcaster."""
        token = await self._get_token()
        started_at = (
            datetime.now(timezone.utc) - timedelta(hours=hours_back)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.twitch.tv/helix/clips",
                headers=self._headers(token),
                params={
                    "broadcaster_id": broadcaster_id,
                    "first": min(max_clips, 100),
                    "started_at": started_at,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json().get("data", [])


def score_clip_drama(clip: dict) -> float:
    """Score a clip 0-10 for drama potential (views + keyword bonus)."""
    title = (clip.get("title") or "").lower()
    views = clip.get("view_count", 0) or 0

    view_score = math.log10(max(views, 1)) / 7 * 5
    keyword_hits = sum(1 for kw in DRAMA_KEYWORDS if kw in title)
    keyword_score = min(keyword_hits * 0.4, 3.0)

    return view_score + keyword_score


_twitch_client: TwitchApiClient | None = None


def get_twitch_client() -> TwitchApiClient:
    global _twitch_client
    if _twitch_client is None:
        _twitch_client = TwitchApiClient()
    return _twitch_client
