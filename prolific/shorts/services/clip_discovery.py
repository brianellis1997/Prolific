"""Multi-platform clip discovery via yt-dlp search and Tavily web search."""

import logging
import re

from prolific.core.config import settings

logger = logging.getLogger(__name__)

VIDEO_URL_PATTERN = re.compile(
    r"(https?://(?:www\.)?(?:"
    r"youtube\.com/(?:watch\?v=|shorts/|clip/)|"
    r"youtu\.be/|"
    r"clips\.twitch\.tv/|"
    r"twitch\.tv/\w+/clip/|"
    r"kick\.com/(?:clip/|\w+/clips/)|"
    r"clips\.kick\.com/|"
    r"reddit\.com/r/\w+/comments/\w+|"
    r"v\.redd\.it/"
    r")[^\s\"\')]+)",
    re.IGNORECASE,
)


async def discover_clips(
    topic: str,
    niche: str = "general",
    max_clips: int = 5,
) -> list[dict]:
    """Discover relevant video clips across platforms.

    Returns list of dicts with: url, title, creator, view_count, duration, platform
    """
    results = []

    yt_results = await _search_youtube(topic, max_clips)
    results.extend(yt_results)

    web_results = await _search_web_for_clips(topic, niche)
    results.extend(web_results)

    seen_urls = set()
    unique = []
    for r in results:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(r)

    unique.sort(key=lambda r: r.get("view_count", 0) or 0, reverse=True)
    logger.info(f"Discovered {len(unique)} unique clips for '{topic}'")
    return unique[:max_clips]


async def _search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube via yt-dlp for relevant clips."""
    try:
        from prolific.shorts.services.clip_downloader import get_clip_downloader
        import asyncio
        import json

        downloader = get_clip_downloader()
        search_query = f"ytsearch{max_results}:{query}"

        cmd = [
            downloader.yt_dlp,
            "--dump-json",
            "--no-download",
            "--no-warnings",
            "--flat-playlist",
            search_query,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0 or not stdout:
            return []

        results = []
        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                results.append({
                    "url": info.get("url") or f"https://www.youtube.com/watch?v={info.get('id', '')}",
                    "title": info.get("title", ""),
                    "creator": info.get("uploader", info.get("channel", "")),
                    "view_count": info.get("view_count", 0) or 0,
                    "duration": info.get("duration", 0) or 0,
                    "platform": "youtube",
                })
            except Exception:
                continue

        return results

    except Exception as e:
        logger.warning(f"YouTube search failed: {e}")
        return []


async def _search_web_for_clips(topic: str, niche: str = "general") -> list[dict]:
    """Search the web via Tavily for posts linking to video clips."""
    try:
        from prolific.services.web_search import get_web_search_service
        search_service = get_web_search_service()

        niche_terms = {
            "twitch": "twitch clip viral",
            "sports": "highlight clip video",
            "celebrity": "video clip footage",
            "curiosity": "viral video clip",
            "general": "video clip",
        }
        suffix = niche_terms.get(niche, "video clip")
        query = f"{topic} {suffix}"

        results = await search_service.search(
            query=query,
            max_results=10,
            search_depth="basic",
        )

        clips = []
        for r in results or []:
            url = getattr(r, "url", "")
            title = getattr(r, "title", "")
            snippet = getattr(r, "snippet", "")

            video_urls = VIDEO_URL_PATTERN.findall(url)
            if video_urls:
                clips.append({
                    "url": video_urls[0],
                    "title": title,
                    "creator": "",
                    "view_count": 0,
                    "duration": 0,
                    "platform": _detect_platform(video_urls[0]),
                })
            else:
                text_urls = VIDEO_URL_PATTERN.findall(snippet)
                for vurl in text_urls:
                    clips.append({
                        "url": vurl,
                        "title": title,
                        "creator": "",
                        "view_count": 0,
                        "duration": 0,
                        "platform": _detect_platform(vurl),
                    })

        return clips

    except Exception as e:
        logger.warning(f"Web clip search failed: {e}")
        return []


async def verify_clip_available(url: str) -> dict | None:
    """Quick check if a clip URL is downloadable. Returns info or None."""
    try:
        from prolific.shorts.services.clip_downloader import get_clip_downloader
        downloader = get_clip_downloader()
        return await downloader.get_clip_info(url)
    except Exception:
        return None


def _detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "twitch" in url_lower:
        return "twitch"
    elif "youtube" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "reddit" in url_lower:
        return "reddit"
    return "other"
