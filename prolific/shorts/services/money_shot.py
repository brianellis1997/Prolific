"""Money-shot sourcing — find the ACTUAL footage of a specific event, legally.

Stock libraries (Pexels/Pixabay) only have generic b-roll: a generic octopus,
not "an octopus punching a fish." That generic-payload gap is the ceiling on
shorts virality — we hook the viewer but never show the thing we promised.

This service searches YouTube for the SPECIFIC event, but restricted to
Creative-Commons-licensed videos (legally reusable with attribution), downloads
the best candidate, and uses a vision model to VERIFY the footage actually shows
the event before we commit to it. Anything not confirmed is discarded so we fall
back to stock rather than ship a mislabeled clip.

Copyright stance: ONLY Creative Commons / reuse-allowed videos are used. Standard
YouTube License videos are filtered out — using them risks Content ID claims and
channel strikes, which for a channel we just clawed back from a throttle is not a
trade worth making. Attribution for each used clip is returned so it can be
appended to the video description (CC-BY requirement).
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from prolific.core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class MoneyShotResult:
    """A verified, downloaded, reuse-licensed clip of a specific event."""

    file_path: str
    source_url: str
    title: str
    creator: str
    license: str = "Creative Commons (YouTube reuse-allowed)"


class _MoneyShotPick(__import__("pydantic").BaseModel):
    scene_index: int
    search_query: str       # what to search YouTube for, e.g. "octopus punching fish"
    event_description: str  # what the vision model must confirm is on-screen


class _MoneyShotPlan(__import__("pydantic").BaseModel):
    picks: list[_MoneyShotPick]


async def identify_money_shots(
    topic: str, scene_texts: list[str], max_picks: int = 2,
) -> list[_MoneyShotPick]:
    """Pick the 1-2 scenes whose specific real footage would most boost the short.

    Returns the scene indexes plus a precise YouTube search query and a vision
    description for each. These are the "payoff" moments — the actual event the
    narration promises (the octopus punch), not generic b-roll. Returns [] if no
    scene has a findable specific real-world action.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from prolific.services.llm import get_llm_service

    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(scene_texts))
    system = (
        "You pick the 'money shot' moments for a short video — the 1-2 scenes "
        "where showing the ACTUAL real-world footage of the specific event (not "
        "generic stock b-roll) would most make the video pop. Only pick a scene "
        "if it describes a SPECIFIC, filmable real-world action or sight that "
        "real footage would plausibly exist for (an animal doing a specific "
        "thing, a named place, a physical phenomenon). Skip abstract/narration-"
        "only scenes.\n\n"
        "For each pick give: scene_index, a concise literal YouTube search query "
        "for the real footage (e.g. 'octopus punching fish', 'starfish eating "
        "mussel time lapse'), and event_description — a plain sentence of what a "
        "verifier must SEE on screen to confirm the clip is right.\n"
        f"Pick at most {max_picks}. If nothing qualifies, return an empty list."
    )
    try:
        llm = get_llm_service()
        plan = await llm.invoke_with_structured_output(
            messages=[
                SystemMessage(content=system),
                HumanMessage(content=f"TOPIC: {topic}\n\nSCENES:\n{numbered}"),
            ],
            output_schema=_MoneyShotPlan,
            tier="research",
            temperature=0.2,
        )
        picks = [p for p in (plan.picks or []) if 0 <= p.scene_index < len(scene_texts)]
        return picks[:max_picks]
    except Exception as exc:
        logger.warning(f"identify_money_shots failed: {exc}")
        return []


def _get_search_client():
    """Build a YouTube Data API client for CC search.

    Uses a dedicated read-only API key if YOUTUBE_DATA_API_KEY is set (keeps
    search quota off the OAuth upload credentials); otherwise falls back to the
    shorts channel's OAuth credentials, which can also run search.list.
    """
    from googleapiclient.discovery import build

    api_key = getattr(settings, "youtube_data_api_key", "") or ""
    if api_key:
        return build("youtube", "v3", developerKey=api_key)

    # Fall back to shorts OAuth creds (SHORTS_CREDENTIALS_B64 env or file).
    import base64
    import os
    from google.oauth2.credentials import Credentials

    raw = None
    b64 = os.environ.get("SHORTS_CREDENTIALS_B64")
    if b64:
        raw = json.loads(base64.b64decode(b64))
    elif Path(settings.shorts_credentials_path).exists():
        raw = json.loads(Path(settings.shorts_credentials_path).read_text())
    if not raw:
        raise RuntimeError("No YOUTUBE_DATA_API_KEY and no shorts credentials for CC search")
    creds = Credentials(
        token=raw.get("token"), refresh_token=raw.get("refresh_token"),
        token_uri=raw.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=raw.get("client_id"), client_secret=raw.get("client_secret"),
    )
    return build("youtube", "v3", credentials=creds)


async def _search_cc_candidates(query: str, max_results: int = 6) -> list[dict]:
    """Find Creative-Commons-licensed YouTube videos for a specific event.

    Uses the Data API's videoLicense=creativeCommon filter (yt-dlp's license
    field is unreliable — returns None even for CC videos). Restricts to short
    videos so we get focused clips, not long compilations/documentaries.
    """
    def _search():
        yt = _get_search_client()
        resp = yt.search().list(
            part="snippet",
            q=query,
            type="video",
            videoLicense="creativeCommon",
            videoDuration="short",   # < 4 min — focused clips, small downloads
            safeSearch="moderate",
            maxResults=max_results,
            order="relevance",
        ).execute()
        out = []
        for it in resp.get("items", []):
            vid = it["id"]["videoId"]
            out.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": it["snippet"]["title"],
                "creator": it["snippet"]["channelTitle"],
            })
        return out

    try:
        cands = await asyncio.get_event_loop().run_in_executor(None, _search)
        logger.info(f"money-shot: {len(cands)} CC candidates for '{query}'")
        return cands
    except Exception as exc:
        logger.warning(f"money-shot CC search failed for '{query}': {exc}")
        return []


def _extract_frame_b64(video_path: str) -> str | None:
    """Grab a representative frame (~40% in) as base64 JPEG for vision check."""
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not Path(video_path).exists():
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            frame_path = tf.name
        # Seek to a point likely to contain the action, not the intro frame.
        subprocess.run(
            [ffmpeg, "-y", "-ss", "1.5", "-i", video_path, "-frames:v", "1",
             "-q:v", "4", frame_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        data = Path(frame_path).read_bytes()
        Path(frame_path).unlink(missing_ok=True)
        if not data:
            return None
        return base64.b64encode(data).decode()
    except Exception as exc:
        logger.warning(f"money-shot frame extract failed: {exc}")
        return None


class _MoneyShotVerdict(__import__("pydantic").BaseModel):
    shows_event: bool
    what_is_actually_shown: str


async def _verify_shows_event(event_description: str, frame_b64: str) -> bool:
    """Vision check: does this frame actually depict the promised event?"""
    from prolific.services.llm import get_llm_service

    prompt = (
        "You are verifying whether a downloaded video clip actually shows a "
        "specific event we want to use it for. Be strict — if it only shows the "
        "subject generically (e.g. an octopus just sitting there) but NOT the "
        "specific action, answer false.\n\n"
        f"THE EVENT WE NEED TO SEE: \"{event_description}\"\n\n"
        "Look at this frame from the clip. Does it genuinely show that event (or "
        "a moment clearly part of it)? Set shows_event=true only if a viewer "
        "would recognize this as the event, and describe what_is_actually_shown."
    )
    try:
        llm = get_llm_service()
        verdict = await llm.invoke_with_image_structured(
            prompt=prompt,
            image_base64=frame_b64,
            output_schema=_MoneyShotVerdict,
            image_format="jpg",
            tier="vision",
            temperature=0.0,
        )
        if verdict.shows_event:
            logger.info(f"money-shot VERIFIED: '{event_description}' — {verdict.what_is_actually_shown[:80]}")
        else:
            logger.info(f"money-shot rejected: frame shows '{verdict.what_is_actually_shown[:80]}'")
        return bool(verdict.shows_event)
    except Exception as exc:
        logger.warning(f"money-shot vision verify failed: {exc}")
        return False


async def find_verified_cc_clip(
    event_query: str,
    event_description: str,
    output_dir: str,
    filename: str,
    duration_seconds: float,
    width: int = 1080,
    height: int = 1920,
    max_candidates: int = 4,
) -> MoneyShotResult | None:
    """Find, download, and VERIFY a Creative-Commons clip of a specific event.

    event_query:       what to search YouTube for ("octopus punching fish")
    event_description:  what the vision model must confirm is on-screen
    Returns a MoneyShotResult (with attribution) only if a CC clip was found,
    downloaded, AND vision-confirmed to show the event. Otherwise None — caller
    falls back to stock.
    """
    if not settings.shorts_money_shot_enabled:
        return None

    from prolific.shorts.services.clip_downloader import get_clip_downloader

    candidates = await _search_cc_candidates(event_query, max_results=max_candidates + 2)
    if not candidates:
        return None

    downloader = get_clip_downloader()
    for i, cand in enumerate(candidates[:max_candidates]):
        dl = await downloader.download_clip(
            cand["url"], output_dir, f"{filename}_cc{i}", max_duration=int(max(duration_seconds, 8)),
        )
        if not dl:
            continue
        clip_path, _audio = dl
        frame = _extract_frame_b64(clip_path)
        if not frame:
            Path(clip_path).unlink(missing_ok=True)
            continue
        if await _verify_shows_event(event_description, frame):
            return MoneyShotResult(
                file_path=clip_path,
                source_url=cand["url"],
                title=cand["title"],
                creator=cand["creator"],
            )
        # Not the event — discard and try the next candidate.
        Path(clip_path).unlink(missing_ok=True)

    logger.info(f"money-shot: no CC candidate verified for '{event_query}'")
    return None
