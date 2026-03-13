"""Pexels Video API client for sourcing stock clips."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)

PEXELS_BASE_URL = "https://api.pexels.com"


class PexelsService:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.pexels_api_key
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY not configured")
        self.ffmpeg = shutil.which("ffmpeg")

    async def search_videos(
        self,
        query: str,
        orientation: str = "portrait",
        per_page: int = 5,
    ) -> list[dict]:
        """Search Pexels for videos. Returns list of video result dicts."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{PEXELS_BASE_URL}/videos/search",
                headers={"Authorization": self.api_key},
                params={
                    "query": query,
                    "orientation": orientation,
                    "per_page": per_page,
                    "size": "medium",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("videos", [])

    def _pick_best_file(self, video: dict, prefer_portrait: bool = True) -> dict | None:
        """Pick the best video file from a Pexels result (prefer HD portrait)."""
        files = video.get("video_files", [])
        if not files:
            return None

        portrait_files = [
            f for f in files
            if f.get("height", 0) > f.get("width", 0)
        ]
        candidates = portrait_files if (prefer_portrait and portrait_files) else files

        candidates.sort(key=lambda f: f.get("height", 0), reverse=True)
        for f in candidates:
            if f.get("height", 0) >= 720:
                return f
        return candidates[0] if candidates else None

    async def download_video(self, url: str, output_path: str) -> str:
        """Download a video file from URL."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            Path(output_path).write_bytes(resp.content)

        logger.info(f"Downloaded video: {output_path} ({Path(output_path).stat().st_size // 1024}KB)")
        return output_path

    async def trim_and_resize(
        self,
        input_path: str,
        output_path: str,
        duration: float = 2.5,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
        """Trim video to duration and resize/crop to target resolution."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

        cmd = [
            self.ffmpeg,
            "-i", input_path,
            "-ss", "0",
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-an",
            "-y",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode()[-500:] if stderr else "unknown error"
            raise RuntimeError(f"ffmpeg trim/resize failed: {error_msg}")

        logger.info(f"Trimmed clip: {output_path} ({duration}s, {width}x{height})")
        return output_path

    async def fetch_clip(
        self,
        query: str,
        output_path: str,
        duration: float = 2.5,
        width: int = 1080,
        height: int = 1920,
    ) -> str | None:
        """Search, download, trim and resize a stock clip. Returns path or None."""
        try:
            videos = await self.search_videos(query)
            if not videos:
                logger.warning(f"No Pexels results for '{query}'")
                return None

            for video in videos:
                best_file = self._pick_best_file(video)
                if not best_file:
                    continue

                raw_path = str(Path(output_path).parent / f"raw_{Path(output_path).name}")
                await self.download_video(best_file["link"], raw_path)
                result = await self.trim_and_resize(raw_path, output_path, duration, width, height)
                Path(raw_path).unlink(missing_ok=True)
                return result

            logger.warning(f"No suitable video files for '{query}'")
            return None

        except Exception as e:
            logger.error(f"Pexels fetch failed for '{query}': {e}")
            return None


_pexels_service: PexelsService | None = None


def get_pexels_service() -> PexelsService:
    global _pexels_service
    if _pexels_service is None:
        _pexels_service = PexelsService()
    return _pexels_service
