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
    license_kind: str = "cc"
    match: str = "event"
    source_path: str = ""
    source_seconds: float = 0.0
    source_start: float = 0.0
    source_window: float = 0.0


class _MoneyShotPick(__import__("pydantic").BaseModel):
    scene_index: int
    search_query: str       # simple literal visual search, e.g. "octopus punching fish"
    fallback_query: str = ""  # broader retry if the specific search finds nothing
    event_description: str  # what the vision model must confirm is on-screen
    subject: str = ""


class _MoneyShotPlan(__import__("pydantic").BaseModel):
    picks: list[_MoneyShotPick]


async def identify_money_shots(
    topic: str, scene_texts: list[str], max_picks: int = 2,
) -> list[_MoneyShotPick]:
    """Pick the 1-2 scenes whose specific real footage would most boost the short.

    Returns the scene indexes plus a simple YouTube search query, a broader
    fallback query, and a vision description for each. These are the "payoff"
    moments — the actual event the narration promises (the octopus punch), not
    generic b-roll. Returns [] if no scene has a findable VISUAL real-world action.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from prolific.services.llm import get_llm_service

    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(scene_texts))
    system = (
        "You pick the scenes of a short video where ACTUAL real-world footage of the "
        "specific subject or event (not generic stock b-roll) would most make the video "
        "pop. Each scene line is the exact words the voice says while that clip is on "
        "screen, and the clip must show what those words describe at that moment.\n\n"
        "Rank scenes by how specific and visual the spoken words are. A scene that names "
        "an action or event (a cow pulled away from her friend, two cows reunited, an "
        "octopus punching a fish) comes before a scene that only names the animal, and a "
        "scene that only names the animal comes before nothing. Never pick a generic scene "
        "('cows grazing in a field') while a scene with a specific action is unpicked.\n\n"
        "ONLY pick a scene whose payoff is something you could literally SEE on "
        "camera: an animal visibly doing a thing, a physical event, a real place. "
        "SKIP anything that is a SOUND, a statistic, a sensor reading, an internal/"
        "microscopic process, or an abstract concept — there is no footage of "
        "'bees whooping' (a sound) or 'a lobster being biologically immortal'.\n\n"
        "The search_query is the SINGLE most important thing. Write it the way an "
        "uploader would title a video of that exact moment, 2 to 6 simple, common words, "
        "using the event words from the narration: 'cow reunited with best friend', "
        "'calf separated from mother', 'crows gather around dead crow'. Never swap the "
        "event for a weaker stand-in ('cow running to fence' is wrong for a scene about "
        "separation). NOT scientific or technical wording.\n"
        "  GOOD: 'octopus punching fish', 'starfish eating mussel', 'eagle catching "
        "fish', 'volcano lava fountain', 'mantis shrimp punch'\n"
        "  BAD:  'honeybee hive vibration sensors accelerometer' (technical, no such "
        "footage), 'cephalopod aggressive territorial behavior' (jargon), "
        "'apoptosis cellular senescence' (microscopic/abstract)\n\n"
        "Also give a fallback_query: another title for the SAME moment in different "
        "words, a little broader (e.g. 'mantis shrimp punching snail' -> 'mantis shrimp "
        "strike'; 'cow separated from friend' -> 'cows crying for each other'). And "
        "event_description: a plain sentence "
        "of what a verifier must SEE on screen. And subject: the exact animal, object or "
        "place the whole short is about (e.g. 'naked mole rat'), even when the scene "
        "shows something else.\n"
        f"Pick up to {max_picks} scenes, each a different scene. If no scene has a "
        "genuinely filmable visual payoff, return an empty list — do not force it."
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


_BLOCKED_SOURCE_PATTERN = __import__("re").compile(
    r"\b(bbc|national geographic|nat ?geo|discovery|animal planet|pbs|smithsonian|netflix|disney|"
    r"nbc|cbs|abc news|fox news|cnn|sky news|itv|channel 4|paramount|warner|universal pictures|"
    r"sony pictures|viralhog|viral hog|jukin|newsflare|storyful|caters|rumble|reuters|associated press|"
    r"ap archive|bloomberg|wildearth|bbc earth)\b"
)
_BLOCKED_DESCRIPTION_PATTERN = __import__("re").compile(
    r"\b(viralhog|viral hog|jukin|newsflare|storyful|caters|for licensing|to license|licensing@|rumble\.com)\b"
)


_NETWORK_IN_TEXT_PATTERN = __import__("re").compile(
    r"\b(bbc|national geographic|nat ?geo|discovery channel|animal planet|pbs|smithsonian channel|netflix|"
    r"disney|nbc|cbs|abc news|fox news|cnn|sky news|reuters|associated press|ap archive|bloomberg|"
    r"attenborough|planet earth|blue planet|frozen planet|our planet|seven worlds|dynasties)\b"
)
_EXPLAINER_TITLE_PATTERN = __import__("re").compile(
    r"^\s*(why|how|what|this is why|here'?s why|the (real|secret|hidden|true|actual) reason)\b"
    r"|\bexplained\b|\bfacts?\b|\bdid you know\b|\bthe truth about\b|\byou won'?t believe\b"
)
_STOCK_SELLER_PATTERN = __import__("re").compile(r"\bstock\b|\bfootage (library|agency|licensing)\b|\bb-?roll\b")
_REUPLOAD_PATTERN = __import__("re").compile(
    r"\b(compilation|re-?upload(?:ed)?|all rights reserved|copyright|courtesy of|fair use|"
    r"i do not own|i don'?t own|not my (?:video|footage)|top \d+)\b"
    r"|\bcredits?\b\s*(?:to|goes|go|:)|\bfootage (?:by|from)\b|\bvideo (?:by|credit)\b|©"
)


def is_blocked_source(channel: str, description: str) -> bool:
    return bool(
        _BLOCKED_SOURCE_PATTERN.search((channel or "").lower())
        or _BLOCKED_DESCRIPTION_PATTERN.search((description or "").lower())
    )


def is_reupload(title: str, description: str) -> bool:
    text = f"{title or ''}\n{description or ''}".lower()
    return bool(_NETWORK_IN_TEXT_PATTERN.search(text) or _REUPLOAD_PATTERN.search(text))


def vet_candidate(item: dict, video_license: str) -> str:
    snippet, status = item.get("snippet", {}), item.get("status", {})
    details = item.get("contentDetails", {})
    if video_license == "creativeCommon" and status.get("license") != "creativeCommon":
        return "license is not creativeCommon"
    if details.get("licensedContent"):
        return "managed by a Content ID partner"
    if is_blocked_source(snippet.get("channelTitle", ""), snippet.get("description", "")):
        return "blocked source"
    if is_reupload(snippet.get("title", ""), snippet.get("description", "")):
        return "looks like a re-upload"
    if _EXPLAINER_TITLE_PATTERN.search((snippet.get("title") or "").lower()):
        return "explainer title (another facts channel)"
    if status.get("license") != "creativeCommon" and _STOCK_SELLER_PATTERN.search((snippet.get("channelTitle") or "").lower()):
        return "stock footage seller (not CC)"
    return ""


_WEB_SEARCH_CACHE: dict[tuple[str, bool], list[dict]] = {}


async def _web_search(query: str, cc_only: bool, limit: int = 30) -> list[dict] | None:
    from urllib.parse import quote_plus

    from prolific.shorts.services.clip_downloader import get_clip_downloader, proxy_url

    key = (query.strip().lower(), cc_only)
    if key in _WEB_SEARCH_CACHE:
        return _WEB_SEARCH_CACHE[key]
    target = (
        f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp=EgIwAQ%253D%253D"
        if cc_only else f"ytsearch{limit}:{query}"
    )
    yt_dlp = get_clip_downloader().yt_dlp
    for _ in range(3):
        proxy = proxy_url()
        proc = await asyncio.create_subprocess_exec(
            yt_dlp, *(["--proxy", proxy] if proxy else []), "--flat-playlist", "-J", "--no-warnings",
            "--playlist-end", str(limit), target,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, _err = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            continue
        if proc.returncode != 0:
            continue
        try:
            entries = [
                {"id": e["id"], "duration": e.get("duration")}
                for e in json.loads(out.decode()).get("entries", []) if e.get("id")
            ]
        except (ValueError, KeyError, AttributeError):
            continue
        if len(_WEB_SEARCH_CACHE) > 300:
            _WEB_SEARCH_CACHE.clear()
        _WEB_SEARCH_CACHE[key] = entries
        return entries
    logger.warning(f"money-shot web search failed for '{query}', using the Data API")
    return None


def duration_band(video_duration: str) -> tuple[float, float]:
    return (0.0, 240.0) if video_duration == "short" else (240.0, 1200.0)


async def _search_candidates(
    query: str, video_license: str, max_results: int = 8, video_duration: str = "short",
) -> list[dict]:
    entries = await _web_search(query, cc_only=video_license == "creativeCommon")

    def _search():
        yt = _get_search_client()
        if entries is None:
            resp = yt.search().list(
                part="snippet", q=query, type="video", videoLicense=video_license,
                videoDuration=video_duration, safeSearch="moderate", maxResults=max_results, order="relevance",
            ).execute()
            ids = [it["id"]["videoId"] for it in resp.get("items", [])]
        else:
            low, high = duration_band(video_duration)
            ids = [e["id"] for e in entries if e.get("duration") and low < float(e["duration"]) <= high][: max_results * 2]
        if not ids:
            return []
        details = yt.videos().list(part="snippet,status,contentDetails", id=",".join(ids)).execute()
        by_id = {it["id"]: it for it in details.get("items", [])}
        out = []
        for vid in ids:
            item = by_id.get(vid)
            if not item:
                continue
            reason = vet_candidate(item, video_license)
            if reason:
                logger.info(f"money-shot: skipped {vid} '{item['snippet'].get('channelTitle', '')}': {reason}")
                continue
            out.append({
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": item["snippet"]["title"],
                "creator": item["snippet"]["channelTitle"],
                "channel_id": item["snippet"].get("channelId", ""),
                "license_kind": "cc" if item.get("status", {}).get("license") == "creativeCommon" else "fair_use",
            })
        return out[:max_results]

    try:
        cands = await asyncio.get_event_loop().run_in_executor(None, _search)
        logger.info(f"money-shot: {len(cands)} {video_license} {video_duration} candidates for '{query}'")
        return cands
    except Exception as exc:
        logger.warning(f"money-shot search failed for '{query}' ({video_license}): {exc}")
        return []


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


def _probe_duration(video_path: str) -> float:
    """Return clip duration in seconds (0.0 if unknown)."""
    import shutil
    import subprocess

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, timeout=20,
        )
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _extract_frames_montage_b64(video_path: str, num_frames: int = 4) -> str | None:
    """Sample N frames evenly across the clip and tile them into one image.

    A single early frame misses action that happens later in the clip (the
    starfish doesn't eat at second 1.5). Sampling across the whole clip and
    checking them together in ONE vision call catches the moment wherever it
    occurs, without multiplying vision cost. Falls back to a single mid-clip
    frame if duration can't be probed.
    """
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not Path(video_path).exists():
        return None

    dur = _probe_duration(video_path)
    # Even fractions across the clip, avoiding the very first/last frames.
    if dur and dur > 0.5:
        fracs = [(i + 1) / (num_frames + 1) for i in range(num_frames)]
        timestamps = [round(f * dur, 2) for f in fracs]
    else:
        timestamps = [1.5]  # fallback: single frame

    try:
        from PIL import Image

        frame_imgs = []
        tmpdir = tempfile.mkdtemp(prefix="ms_frames_")
        for idx, ts in enumerate(timestamps):
            fp = str(Path(tmpdir) / f"f{idx}.jpg")
            subprocess.run(
                [ffmpeg, "-y", "-ss", str(ts), "-i", video_path, "-frames:v", "1",
                 "-q:v", "4", fp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
            if Path(fp).exists() and Path(fp).stat().st_size > 0:
                frame_imgs.append(Image.open(fp).convert("RGB"))

        if not frame_imgs:
            return None
        if len(frame_imgs) == 1:
            import io
            buf = io.BytesIO()
            frame_imgs[0].save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode()

        # Tile into a horizontal strip, each frame scaled to a common height.
        target_h = 360
        scaled = []
        for im in frame_imgs:
            w = int(im.width * target_h / im.height)
            scaled.append(im.resize((w, target_h)))
        total_w = sum(im.width for im in scaled)
        montage = Image.new("RGB", (total_w, target_h), (0, 0, 0))
        x = 0
        for im in scaled:
            montage.paste(im, (x, 0))
            x += im.width

        import io
        buf = io.BytesIO()
        montage.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        logger.warning(f"money-shot montage extract failed: {exc}")
        return None


class _MoneyShotVerdict(__import__("pydantic").BaseModel):
    shows_event: bool
    what_is_actually_shown: str


async def _verify_shows_event(event_description: str, frame_b64: str) -> bool:
    """Vision check: do ANY of the sampled frames depict the promised event?

    The image is a horizontal strip of frames sampled across the clip in time
    order, so the action is caught wherever in the clip it happens."""
    from prolific.services.llm import get_llm_service

    prompt = (
        "You are verifying whether a downloaded video clip actually shows a "
        "specific event we want to use it for. The image below is a STRIP of "
        "several frames sampled across the clip from start to end (left to "
        "right). Be strict about the event, but lenient about WHICH frame: if "
        "ANY frame in the strip clearly shows the event (or a moment plainly "
        "part of it), that counts. If the frames only show the subject "
        "generically (e.g. an octopus just sitting there, a title card, a "
        "resting animal) but never the specific action, answer false.\n\n"
        f"THE EVENT WE NEED TO SEE: \"{event_description}\"\n\n"
        "Set shows_event=true only if at least one frame would make a viewer "
        "recognize the event, and describe what_is_actually_shown across the strip."
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
    fallback_query: str = "",
) -> MoneyShotResult | None:
    """Find, download, and VERIFY a Creative-Commons clip of a specific event.

    event_query:       what to search YouTube for ("octopus punching fish")
    event_description:  what the vision model must confirm is on-screen
    fallback_query:     broader retry if the specific query finds no CC candidates
    Returns a MoneyShotResult (with attribution) only if a CC clip was found,
    downloaded, AND vision-confirmed to show the event. Otherwise None — caller
    falls back to stock.
    """
    if not settings.shorts_money_shot_enabled:
        return None

    from prolific.shorts.services.clip_downloader import get_clip_downloader

    candidates = await _search_cc_candidates(event_query, max_results=max_candidates + 2)
    if not candidates and fallback_query and fallback_query.strip().lower() != event_query.strip().lower():
        logger.info(f"money-shot: retrying with broader query '{fallback_query}'")
        candidates = await _search_cc_candidates(fallback_query, max_results=max_candidates + 2)
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
        montage = _extract_frames_montage_b64(clip_path, num_frames=4)
        if not montage:
            Path(clip_path).unlink(missing_ok=True)
            continue
        if await _verify_shows_event(event_description, montage):
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


class _MoneyShotLocate(__import__("pydantic").BaseModel):
    shows_event: bool
    shows_subject: bool = False
    best_frame: int = 0
    burned_in_mark: str = ""
    what_is_actually_shown: str = ""


def same_owner(mark: str, creator: str) -> bool:
    norm = lambda t: __import__("re").sub(r"[^a-z0-9]", "", (t or "").lower())
    mark_n, creator_n = norm(mark), norm(creator)
    if not mark_n:
        return True
    if creator_n and (creator_n in mark_n or mark_n in creator_n):
        return True
    words = [norm(w) for w in (creator or "").split() if len(norm(w)) >= 4]
    if any(w in mark_n for w in words):
        return True
    overlap = __import__("difflib").SequenceMatcher(None, creator_n, mark_n).find_longest_match(0, len(creator_n), 0, len(mark_n))
    return overlap.size >= min(10, len(creator_n)) > 0


class _UploaderVerdict(__import__("pydantic").BaseModel):
    films_own_footage: bool
    public_domain_archive: bool = False
    reason: str = ""


_UPLOADER_CACHE: dict[str, bool] = {}
_OWN_CHANNEL: dict[str, str] = {}


def _own_channel_id() -> str:
    if "id" not in _OWN_CHANNEL:
        try:
            items = _get_search_client().channels().list(part="id", mine=True).execute().get("items", [])
            _OWN_CHANNEL["id"] = items[0]["id"] if items else ""
        except Exception:
            _OWN_CHANNEL["id"] = ""
    return _OWN_CHANNEL["id"]


async def _uploader_films_own_footage(cand: dict) -> bool:
    channel_id = cand.get("channel_id", "")
    if not channel_id:
        return False
    if channel_id in _UPLOADER_CACHE:
        return _UPLOADER_CACHE[channel_id]

    def _fetch():
        yt = _get_search_client()
        items = yt.channels().list(part="snippet,statistics,contentDetails", id=channel_id).execute().get("items", [])
        if not items:
            return None
        ch = items[0]
        playlist = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        recent = yt.playlistItems().list(part="snippet", playlistId=playlist, maxResults=15).execute().get("items", [])
        return {
            "title": ch["snippet"]["title"],
            "description": ch["snippet"].get("description", "")[:400],
            "videos": ch["statistics"].get("videoCount", "?"),
            "subscribers": ch["statistics"].get("subscriberCount", "?"),
            "recent": [r["snippet"]["title"] for r in recent],
        }

    try:
        info = await asyncio.get_event_loop().run_in_executor(None, _fetch)
    except Exception as exc:
        logger.warning(f"money-shot uploader lookup failed for {channel_id}: {exc}")
        return False
    if not info:
        _UPLOADER_CACHE[channel_id] = False
        return False
    from langchain_core.messages import HumanMessage, SystemMessage
    from prolific.services.llm import get_llm_service

    system = (
        "You decide whether a YouTube channel films its own footage or re-posts other people's footage. "
        "OWN FOOTAGE: a zoo, sanctuary, park, farm, lab, researcher, museum, wildlife filmmaker, diver, hobbyist "
        "or vlogger whose uploads read like their own camera work in their own places. "
        "RE-POSTS: facts or trivia channels, compilations, 'funny animals' or 'daily clips' channels, viral or news "
        "reposts, AI channels, or a channel whose titles jump between unrelated viral topics. Also answer false "
        "for any narrated or animated explainer, facts, history or educational channel, even when it makes its "
        "own animation: those are competitors and their videos carry their own text and voice. "
        "Separately, set public_domain_archive=true only when the channel mainly posts US government films "
        "(military, NASA, NOAA, USGS, National Archives, Department of Energy) or other public domain archive "
        "films, and not newsreels or footage owned by companies (Pathé, Movietone, Getty, AP, Reuters). "
        "When unsure, answer false to both."
    )
    human = (
        f"Channel: {info['title']}\nChannel description: {info['description']}\n"
        f"Videos: {info['videos']}, subscribers: {info['subscribers']}\n"
        "Recent upload titles:\n- " + "\n- ".join(info["recent"]) +
        f"\n\nCandidate video title: {cand.get('title', '')}"
    )
    try:
        verdict = await get_llm_service().invoke_with_structured_output(
            messages=[SystemMessage(content=system), HumanMessage(content=human)],
            output_schema=_UploaderVerdict, tier="research", temperature=0.0,
        )
        own = bool(verdict.films_own_footage or verdict.public_domain_archive)
        kind = "own footage" if verdict.films_own_footage else ("public domain archive" if verdict.public_domain_archive else "re-posts")
        logger.info(f"money-shot uploader '{info['title']}': {kind} ({verdict.reason[:80]})")
    except Exception as exc:
        logger.warning(f"money-shot uploader check failed for {channel_id}: {exc}")
        own = False
    _UPLOADER_CACHE[channel_id] = own
    return own


def _frames_strip(video_path: str, num_frames: int = 6) -> tuple[str | None, list[float]]:
    import io
    import shutil
    import subprocess
    import tempfile

    ffmpeg = shutil.which("ffmpeg")
    dur = _probe_duration(video_path)
    if not ffmpeg or dur <= 0.5:
        return None, []
    times = [round((i + 1) / (num_frames + 1) * dur, 2) for i in range(num_frames)]
    try:
        from PIL import Image, ImageDraw

        frames, kept = [], []
        tmpdir = tempfile.mkdtemp(prefix="ms_strip_")
        for idx, ts in enumerate(times):
            fp = str(Path(tmpdir) / f"f{idx}.jpg")
            subprocess.run(
                [ffmpeg, "-y", "-ss", str(ts), "-i", video_path, "-frames:v", "1", "-q:v", "4", fp],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
            )
            if Path(fp).exists() and Path(fp).stat().st_size > 0:
                im = Image.open(fp).convert("RGB")
                im = im.resize((int(im.width * 300 / im.height), 300))
                draw = ImageDraw.Draw(im)
                draw.rectangle([0, 0, 44, 44], fill=(0, 0, 0))
                draw.text((14, 10), str(len(frames) + 1), fill=(255, 255, 0))
                frames.append(im)
                kept.append(ts)
        if not frames:
            return None, []
        strip = Image.new("RGB", (sum(f.width for f in frames), 300))
        x = 0
        for f in frames:
            strip.paste(f, (x, 0))
            x += f.width
        buf = io.BytesIO()
        strip.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode(), kept
    except Exception as exc:
        logger.warning(f"money-shot strip failed: {exc}")
        return None, []


async def _locate_event(
    event_description: str, strip_b64: str, frame_count: int, subject: str = "",
) -> tuple[bool, int, bool, str]:
    from prolific.services.llm import get_llm_service

    subject_line = (
        f"THE SHORT IS ABOUT: \"{subject}\". Set shows_subject=true only if {subject} itself is clearly "
        "visible and large in at least one frame (that exact species or thing, not a similar one, and not "
        "another animal from the scene), even if it is not doing the event."
        if subject else
        "Set shows_subject=true if the main animal, object or place of the event is clearly visible and "
        "large in at least one frame (the same species or thing, not a similar one), even if it is not "
        "doing the event."
    )
    prompt = (
        "You check whether a downloaded video shows a specific event. The image holds "
        f"{frame_count} frames from the video in time order, numbered 1 to {frame_count} in reading order "
        "(left to right, then the next row). "
        "Be strict about the event: the frames must show the specific action or thing, not only the "
        "subject resting, a title card, a person talking to the camera, or text on screen.\n\n"
        f"THE EVENT WE NEED TO SEE: \"{event_description}\"\n{subject_line}\n\n"
        "Set shows_event=true only if at least one frame clearly shows the event. Set best_frame "
        "to the frame that shows the event most clearly, or else the subject most clearly. Set "
        "burned_in_mark to the exact text of any watermark, @handle, logo or channel name burned into "
        "the frames (not subtitles or captions of what is said), or leave it empty. Describe "
        "what_is_actually_shown."
    )
    try:
        verdict = await get_llm_service().invoke_with_image_structured(
            prompt=prompt, image_base64=strip_b64, output_schema=_MoneyShotLocate,
            image_format="jpg", tier="vision", temperature=0.0,
        )
    except Exception as exc:
        logger.warning(f"money-shot locate failed: {exc}")
        return False, 0, False, ""
    status = "VERIFIED" if verdict.shows_event else ("subject only" if verdict.shows_subject else "rejected")
    mark = (verdict.burned_in_mark or "").strip()
    logger.info(
        f"money-shot {status} (frame {verdict.best_frame}){' mark=' + repr(mark[:40]) if mark else ''}: "
        f"{verdict.what_is_actually_shown[:90]}"
    )
    return bool(verdict.shows_event), int(verdict.best_frame or 0), bool(verdict.shows_subject), mark


def _storyboard_grid(info: dict, num_frames: int = 12, per_row: int = 6, proxy: str = "") -> tuple[str | None, list[float]]:
    import io
    import urllib.request

    from PIL import Image, ImageDraw

    boards = [f for f in info.get("formats", []) if str(f.get("format_id", "")).startswith("sb") and f.get("fragments")]
    duration = float(info.get("duration") or 0)
    if not boards or duration <= 0:
        return None, []
    board = max(boards, key=lambda f: f.get("width") or 0)
    rows, cols, fps = int(board.get("rows") or 0), int(board.get("columns") or 0), float(board.get("fps") or 0)
    tile_w, tile_h = int(board.get("width") or 0), int(board.get("height") or 0)
    if not (rows and cols and fps and tile_w and tile_h):
        return None, []
    starts, t = [], 0.0
    for frag in board["fragments"]:
        starts.append(t)
        t += float(frag.get("duration") or rows * cols / fps)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {}))
    sprites: dict[int, Image.Image] = {}
    frames, times = [], []
    for i in range(num_frames):
        want = duration * (0.04 + 0.92 * (i + 0.5) / num_frames)
        j = max(k for k, st in enumerate(starts) if st <= want)
        idx = min(int((want - starts[j]) * fps), rows * cols - 1)
        try:
            if j not in sprites:
                sprites[j] = Image.open(io.BytesIO(opener.open(board["fragments"][j]["url"], timeout=20).read())).convert("RGB")
        except Exception as exc:
            logger.warning(f"money-shot storyboard fetch failed: {exc}")
            return None, []
        r, c = divmod(idx, cols)
        tile = sprites[j].crop((c * tile_w, r * tile_h, (c + 1) * tile_w, (r + 1) * tile_h)).resize((240, 180))
        draw = ImageDraw.Draw(tile)
        draw.rectangle([0, 0, 30, 24], fill=(0, 0, 0))
        draw.text((6, 5), str(len(frames) + 1), fill=(255, 255, 0))
        frames.append(tile)
        times.append(round(starts[j] + idx / fps, 2))
    grid_rows = (len(frames) + per_row - 1) // per_row
    grid = Image.new("RGB", (240 * per_row, 180 * grid_rows))
    for n, tile in enumerate(frames):
        grid.paste(tile, ((n % per_row) * 240, (n // per_row) * 180))
    buf = io.BytesIO()
    grid.save(buf, format="JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode(), times


async def _try_long_videos(
    event_query: str, licenses: list[str], event_description: str, subject: str, output_dir: str,
    filename: str, duration_seconds: float, skip_urls: set[str], cooling: set[str], own_channel: str,
) -> MoneyShotResult | None:
    from prolific.shorts.services.clip_downloader import get_clip_downloader

    found, seen = [], set(skip_urls)
    for video_license in licenses:
        for cand in await _search_candidates(event_query, video_license, video_duration="medium"):
            if cand["url"] not in seen:
                seen.add(cand["url"])
                found.append(cand)
    downloader = get_clip_downloader()
    tries = 0
    for cand in interleave_licenses(found):
        if tries >= int(getattr(settings, "shorts_money_shot_long_video_tries", 2)):
            break
        if own_channel and cand.get("channel_id") == own_channel:
            continue
        if cand["license_kind"] == "fair_use" and cand.get("channel_id") in cooling:
            continue
        if not await _uploader_films_own_footage(cand):
            continue
        tries += 1
        info, proxy = await downloader.video_info(cand["url"])
        if not info or not (30 <= float(info.get("duration") or 0) <= 1500):
            continue
        grid, times = await asyncio.get_event_loop().run_in_executor(None, lambda: _storyboard_grid(info, proxy=proxy))
        if not grid:
            continue
        shows, best, _, mark = await _locate_event(event_description, grid, len(times), subject)
        if not shows or not same_owner(mark, cand["creator"]):
            continue
        moment = times[best - 1] if 1 <= best <= len(times) else times[len(times) // 2]
        start, seconds = excerpt_window(moment, float(info["duration"]), duration_seconds + 6.0)
        src = await downloader.download_section(info, proxy, output_dir, f"{filename}_lv{tries}", start, start + seconds)
        if not src:
            continue
        strip, strip_times = _frames_strip(src, num_frames=6)
        ok, best2, has_subject2, mark2 = (
            await _locate_event(event_description, strip, len(strip_times), subject) if strip else (False, 0, False, "")
        )
        if not (ok or has_subject2) or not same_owner(mark2, cand["creator"]):
            Path(src).unlink(missing_ok=True)
            continue
        best_time = strip_times[best2 - 1] if 1 <= best2 <= len(strip_times) else strip_times[len(strip_times) // 2]
        logger.info(f"money-shot long video hit: {cand['creator']} {cand['url']} @ {start + best_time:.1f}s")
        result = await _cut_money_shot(src, cand, best_time, output_dir, filename, duration_seconds, "event")
        Path(src).unlink(missing_ok=True)
        if result:
            return result
    return None


def excerpt_window(best_time: float, source_seconds: float, window_seconds: float) -> tuple[float, float]:
    window = min(window_seconds, source_seconds)
    start = max(0.0, best_time - 0.35 * window)
    if start + window > source_seconds:
        start = max(0.0, source_seconds - window)
    return round(start, 2), round(window, 2)


async def _detect_crop(ffmpeg: str, src: str, start: float, seconds: float) -> tuple[int, int, int, int] | None:
    proc = await asyncio.create_subprocess_exec(
        ffmpeg, "-hide_banner", "-ss", f"{start:.2f}", "-t", f"{min(seconds, 3.0):.2f}", "-i", src,
        "-vf", "cropdetect=24:2:0", "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    found = __import__("re").findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err.decode(errors="ignore"))
    if not found:
        return None
    w, h, x, y = (int(v) for v in found[-1])
    return w, h, x, y


async def _cut_portrait(src: str, out: str, start: float, seconds: float, width: int = 1080, height: int = 1920) -> bool:
    import shutil

    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return False
    probe = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
        "-of", "csv=p=0", src, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    raw, _ = await probe.communicate()
    try:
        src_w, src_h = (int(v) for v in raw.decode().strip().split(",")[:2])
    except ValueError:
        return False
    pre = ""
    crop = await _detect_crop(ffmpeg, src, start, seconds)
    if crop and crop[0] * crop[1] < 0.92 * src_w * src_h and crop[0] >= src_w * 0.5 and crop[1] >= src_h * 0.5:
        pre = f"crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]},"
        src_w, src_h = crop[0], crop[1]
    if src_h >= src_w * 1.5:
        graph = f"[0:v]{pre}scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[v]"
    else:
        fg = width
        graph = (
            f"[0:v]{pre}split[a][b];[a]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=24:4,eq=brightness=-0.08[bg];"
            f"[b]scale=-2:{fg},crop='min(iw,{width})':{fg}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{seconds:.2f}", "-i", src,
        "-filter_complex", graph, "-map", "[v]", "-r", "30", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-y", out,
    ]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"money-shot cut failed: {err.decode()[-200:]}")
        return False
    return Path(out).exists()


def interleave_licenses(candidates: list[dict]) -> list[dict]:
    cc_cands = [c for c in candidates if c["license_kind"] == "cc"]
    fair_cands = [c for c in candidates if c["license_kind"] != "cc"]
    return [c for pair in __import__("itertools").zip_longest(cc_cands, fair_cands) for c in pair if c]


def _sources_file() -> Path:
    return Path(getattr(settings, "shorts_history_db_path", "./shorts_history.sqlite")).parent / "money_shot_sources.json"


def recent_fair_use_channels(now: "datetime | None" = None) -> set[str]:
    from datetime import datetime, timedelta

    now = now or datetime.utcnow()
    days = int(getattr(settings, "shorts_money_shot_source_cooldown_days", 30))
    try:
        used = json.loads(_sources_file().read_text())
    except (OSError, ValueError):
        return set()
    return {ch for ch, when in used.items() if now - datetime.fromisoformat(when) < timedelta(days=days)}


def record_fair_use_source(channel_id: str, now: "datetime | None" = None) -> None:
    from datetime import datetime

    if not channel_id:
        return
    path = _sources_file()
    try:
        used = json.loads(path.read_text())
    except (OSError, ValueError):
        used = {}
    used[channel_id] = (now or datetime.utcnow()).isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(used, indent=1))
    except OSError as exc:
        logger.warning(f"money-shot: could not record fair-use source {channel_id}: {exc}")


async def find_verified_clip(
    event_query: str,
    event_description: str,
    output_dir: str,
    filename: str,
    duration_seconds: float,
    fallback_query: str = "",
    max_candidates: int = 5,
    subject: str = "",
    allow_fair_use: bool = True,
    exclude_urls: set[str] | None = None,
    keep_source: bool = False,
) -> MoneyShotResult | None:
    if not settings.shorts_money_shot_enabled:
        return None
    from prolific.shorts.services.clip_downloader import get_clip_downloader

    licenses = ["creativeCommon"]
    if getattr(settings, "shorts_money_shot_license", "cc_only") == "fair_use" and allow_fair_use:
        licenses.append("any")
    exclude_urls = exclude_urls or set()
    cooling = recent_fair_use_channels()
    own_channel = await asyncio.get_event_loop().run_in_executor(None, _own_channel_id)

    async def _gather(query: str) -> list[dict]:
        found, seen = [], set()
        for video_license in licenses:
            for cand in await _search_candidates(query, video_license):
                if cand["url"] not in seen:
                    seen.add(cand["url"])
                    found.append(cand)
        return found

    candidates = await _gather(event_query)
    if fallback_query and fallback_query.strip().lower() != event_query.strip().lower():
        seen_urls = {c["url"] for c in candidates}
        candidates += [c for c in await _gather(fallback_query) if c["url"] not in seen_urls]

    candidates = interleave_licenses(candidates)

    downloader = get_clip_downloader()
    subject_only: tuple[str, float, dict] | None = None
    tried = 0
    for i, cand in enumerate(candidates):
        if tried >= max_candidates:
            break
        if cand["url"] in exclude_urls or (own_channel and cand.get("channel_id") == own_channel):
            continue
        if cand["license_kind"] == "fair_use" and cand.get("channel_id") in cooling:
            logger.info(f"money-shot: skipped {cand['url']}, fair-use source '{cand['creator']}' used in the last 30 days")
            continue
        if not await _uploader_films_own_footage(cand):
            continue
        tried += 1
        src = await downloader.download_source(cand["url"], output_dir, f"{filename}_ms{i}")
        if not src:
            continue
        strip, times = _frames_strip(src, num_frames=6)
        shows, best, has_subject, mark = (
            await _locate_event(event_description, strip, len(times), subject) if strip else (False, 0, False, "")
        )
        best_time = (times[best - 1] if 1 <= best <= len(times) else times[len(times) // 2]) if times else 0.0
        if not same_owner(mark, cand["creator"]):
            logger.info(f"money-shot: skipped {cand['url']}, burned-in mark {mark[:40]!r} is not the uploader")
            Path(src).unlink(missing_ok=True)
            continue
        if shows:
            result = await _cut_money_shot(src, cand, best_time, output_dir, filename, duration_seconds, "event")
            _keep_or_delete(src, result, keep_source)
            if result:
                if subject_only:
                    Path(subject_only[0]).unlink(missing_ok=True)
                return result
            continue
        if has_subject and (
            subject_only is None or (subject_only[2]["license_kind"] != "cc" and cand["license_kind"] == "cc")
        ):
            if subject_only:
                Path(subject_only[0]).unlink(missing_ok=True)
            subject_only = (src, best_time, cand)
            continue
        Path(src).unlink(missing_ok=True)

    try:
        long_hit = await _try_long_videos(
            event_query, licenses, event_description, subject, output_dir, filename, duration_seconds,
            exclude_urls | {c["url"] for c in candidates}, cooling, own_channel,
        )
    except Exception as exc:
        logger.warning(f"money-shot long-video search failed (non-fatal): {exc}")
        long_hit = None
    if long_hit:
        if subject_only:
            Path(subject_only[0]).unlink(missing_ok=True)
        return long_hit

    if subject_only:
        src, best_time, cand = subject_only
        result = await _cut_money_shot(src, cand, best_time, output_dir, filename, duration_seconds, "subject")
        _keep_or_delete(src, result, keep_source)
        if result:
            return result

    logger.info(f"money-shot: no candidate verified for '{event_query}'")
    return None


async def _cut_money_shot(
    src: str, cand: dict, best_time: float, output_dir: str, filename: str, duration_seconds: float, match: str,
) -> MoneyShotResult | None:
    start, seconds = excerpt_window(best_time, _probe_duration(src), duration_seconds + 3.0)
    out = str(Path(output_dir) / f"{filename}.mp4")
    if not await _cut_portrait(src, out, start, seconds):
        return None
    cc = cand["license_kind"] == "cc"
    source_seconds = _probe_duration(src)
    if not cc:
        record_fair_use_source(cand.get("channel_id", ""))
    logger.info(f"money-shot USED ({cand['license_kind']}, {match}): {cand['creator']} {cand['url']} @ {start:.1f}s")
    return MoneyShotResult(
        file_path=out, source_url=cand["url"], title=cand["title"], creator=cand["creator"],
        license="Creative Commons (YouTube reuse-allowed)" if cc else "Short excerpt, used for commentary (fair use)",
        license_kind=cand["license_kind"], match=match,
        source_seconds=source_seconds, source_start=start, source_window=seconds,
    )


def _keep_or_delete(src: str, result: MoneyShotResult | None, keep: bool) -> None:
    if keep and result:
        result.source_path = src
    else:
        Path(src).unlink(missing_ok=True)


def pool_windows(source_seconds: float, shot_seconds: float, used: list[tuple[float, float]], margin: float = 0.5) -> list[float]:
    starts = []
    span = max(0.0, source_seconds - shot_seconds)
    for frac in (0.12, 0.3, 0.48, 0.66, 0.84, 0.95):
        start = round(span * frac, 2)
        if all(start + shot_seconds + margin <= a or start >= a + w + margin for a, w in used):
            starts.append(start)
    return starts


async def cut_pool_window(src: str, out: str, start: float, seconds: float, subject: str) -> bool:
    if not await _cut_portrait(src, out, start, seconds):
        return False
    strip, times = _frames_strip(out, num_frames=3)
    if not strip:
        Path(out).unlink(missing_ok=True)
        return False
    shows, _, has_subject, _ = await _locate_event(f"a clear view of {subject}", strip, len(times), subject)
    if not (shows or has_subject):
        Path(out).unlink(missing_ok=True)
        return False
    return True
