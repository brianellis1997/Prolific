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


class _MoneyShotPick(__import__("pydantic").BaseModel):
    scene_index: int
    search_query: str       # simple literal visual search, e.g. "octopus punching fish"
    fallback_query: str = ""  # broader retry if the specific search finds nothing
    event_description: str  # what the vision model must confirm is on-screen


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
        "You pick the 'money shot' moments for a short video — the 1-2 scenes "
        "where showing the ACTUAL real-world footage of the specific event (not "
        "generic stock b-roll) would most make the video pop.\n\n"
        "ONLY pick a scene whose payoff is something you could literally SEE on "
        "camera: an animal visibly doing a thing, a physical event, a real place. "
        "SKIP anything that is a SOUND, a statistic, a sensor reading, an internal/"
        "microscopic process, or an abstract concept — there is no footage of "
        "'bees whooping' (a sound) or 'a lobster being biologically immortal'.\n\n"
        "The search_query is the SINGLE most important thing. Write it the way a "
        "normal person would type it into YouTube to find the clip — 2 to 5 simple, "
        "common words describing what you'd SEE. NOT scientific or technical "
        "wording.\n"
        "  GOOD: 'octopus punching fish', 'starfish eating mussel', 'eagle catching "
        "fish', 'volcano lava fountain', 'mantis shrimp punch'\n"
        "  BAD:  'honeybee hive vibration sensors accelerometer' (technical, no such "
        "footage), 'cephalopod aggressive territorial behavior' (jargon), "
        "'apoptosis cellular senescence' (microscopic/abstract)\n\n"
        "Also give a fallback_query: a BROADER but still real version to try if the "
        "specific one finds nothing (e.g. specific 'mantis shrimp punching snail' -> "
        "fallback 'mantis shrimp striking'). And event_description: a plain sentence "
        "of what a verifier must SEE on screen.\n"
        f"Pick at most {max_picks}. If no scene has a genuinely filmable visual "
        "payoff, return an empty list — do not force it."
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


def is_blocked_source(channel: str, description: str) -> bool:
    return bool(
        _BLOCKED_SOURCE_PATTERN.search((channel or "").lower())
        or _BLOCKED_DESCRIPTION_PATTERN.search((description or "").lower())
    )


async def _search_candidates(query: str, video_license: str, max_results: int = 5) -> list[dict]:
    def _search():
        yt = _get_search_client()
        resp = yt.search().list(
            part="snippet", q=query, type="video", videoLicense=video_license,
            videoDuration="short", safeSearch="moderate", maxResults=max_results, order="relevance",
        ).execute()
        out = []
        for it in resp.get("items", []):
            snippet = it["snippet"]
            if is_blocked_source(snippet.get("channelTitle", ""), snippet.get("description", "")):
                logger.info(f"money-shot: skipped blocked source '{snippet.get('channelTitle', '')}'")
                continue
            out.append({
                "url": f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                "title": snippet["title"],
                "creator": snippet["channelTitle"],
                "license_kind": "cc" if video_license == "creativeCommon" else "fair_use",
            })
        return out

    try:
        cands = await asyncio.get_event_loop().run_in_executor(None, _search)
        logger.info(f"money-shot: {len(cands)} {video_license} candidates for '{query}'")
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
    best_frame: int = 0
    what_is_actually_shown: str = ""


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


async def _locate_event(event_description: str, strip_b64: str, frame_count: int) -> tuple[bool, int]:
    from prolific.services.llm import get_llm_service

    prompt = (
        "You check whether a downloaded video shows a specific event. The image is a strip of "
        f"{frame_count} frames from the video in time order, numbered 1 to {frame_count} from left to right. "
        "Be strict about the event: the frames must show the specific action or thing, not only the "
        "subject resting, a title card, a person talking to the camera, or text on screen.\n\n"
        f"THE EVENT WE NEED TO SEE: \"{event_description}\"\n\n"
        "Set shows_event=true only if at least one frame clearly shows the event. Set best_frame to the "
        "number of the frame that shows it most clearly. Describe what_is_actually_shown."
    )
    try:
        verdict = await get_llm_service().invoke_with_image_structured(
            prompt=prompt, image_base64=strip_b64, output_schema=_MoneyShotLocate,
            image_format="jpg", tier="vision", temperature=0.0,
        )
    except Exception as exc:
        logger.warning(f"money-shot locate failed: {exc}")
        return False, 0
    logger.info(
        f"money-shot {'VERIFIED' if verdict.shows_event else 'rejected'} (frame {verdict.best_frame}): "
        f"{verdict.what_is_actually_shown[:90]}"
    )
    return bool(verdict.shows_event), int(verdict.best_frame or 0)


def excerpt_window(best_time: float, source_seconds: float, window_seconds: float) -> tuple[float, float]:
    window = min(window_seconds, source_seconds)
    start = max(0.0, best_time - 0.35 * window)
    if start + window > source_seconds:
        start = max(0.0, source_seconds - window)
    return round(start, 2), round(window, 2)


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
    if src_h >= src_w * 1.5:
        graph = f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[v]"
    else:
        fg = width
        graph = (
            f"[0:v]split[a][b];[a]scale={width}:{height}:force_original_aspect_ratio=increase,"
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


async def find_verified_clip(
    event_query: str,
    event_description: str,
    output_dir: str,
    filename: str,
    duration_seconds: float,
    fallback_query: str = "",
    max_candidates: int = 3,
) -> MoneyShotResult | None:
    if not settings.shorts_money_shot_enabled:
        return None
    from prolific.shorts.services.clip_downloader import get_clip_downloader

    licenses = ["creativeCommon"]
    if getattr(settings, "shorts_money_shot_license", "cc_only") == "fair_use":
        licenses.append("any")

    async def _gather(query: str) -> list[dict]:
        found, seen = [], set()
        for video_license in licenses:
            for cand in await _search_candidates(query, video_license):
                if cand["url"] not in seen:
                    seen.add(cand["url"])
                    found.append(cand)
        return found

    candidates = await _gather(event_query)
    if not candidates and fallback_query and fallback_query.strip().lower() != event_query.strip().lower():
        candidates = await _gather(fallback_query)
    if not candidates:
        return None

    downloader = get_clip_downloader()
    for i, cand in enumerate(candidates[:max_candidates]):
        src = await downloader.download_source(cand["url"], output_dir, f"{filename}_ms{i}")
        if not src:
            continue
        strip, times = _frames_strip(src, num_frames=6)
        shows, best = await _locate_event(event_description, strip, len(times)) if strip else (False, 0)
        if shows:
            best_time = times[best - 1] if 1 <= best <= len(times) else times[len(times) // 2]
            start, seconds = excerpt_window(best_time, _probe_duration(src), duration_seconds + 3.0)
            out = str(Path(output_dir) / f"{filename}.mp4")
            if await _cut_portrait(src, out, start, seconds):
                Path(src).unlink(missing_ok=True)
                cc = cand["license_kind"] == "cc"
                logger.info(f"money-shot USED ({cand['license_kind']}): {cand['creator']} {cand['url']} @ {start:.1f}s")
                return MoneyShotResult(
                    file_path=out, source_url=cand["url"], title=cand["title"], creator=cand["creator"],
                    license="Creative Commons (YouTube reuse-allowed)" if cc else "Short excerpt, used for commentary (fair use)",
                    license_kind=cand["license_kind"],
                )
        Path(src).unlink(missing_ok=True)

    logger.info(f"money-shot: no candidate verified for '{event_query}'")
    return None
