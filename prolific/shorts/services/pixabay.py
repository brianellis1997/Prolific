"""Pixabay Video API client for sourcing stock clips."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)

PIXABAY_BASE_URL = "https://pixabay.com/api/videos/"


class PixabayService:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.pixabay_api_key
        if not self.api_key:
            raise ValueError("PIXABAY_API_KEY not configured")
        self.ffmpeg = shutil.which("ffmpeg")

    async def search_videos(
        self,
        query: str,
        per_page: int = 5,
        page: int = 1,
    ) -> list[dict]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                PIXABAY_BASE_URL,
                params={
                    "key": self.api_key,
                    "q": query,
                    "per_page": per_page,
                    "page": page,
                    "video_type": "film",
                    "safesearch": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("hits", [])

    def _pick_best_file(self, video: dict) -> str | None:
        videos = video.get("videos", {})
        for quality in ("large", "medium", "small"):
            entry = videos.get(quality, {})
            url = entry.get("url")
            if url and entry.get("height", 0) >= 480:
                return url
        return None

    async def download_video(self, url: str, output_path: str) -> str:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            Path(output_path).write_bytes(resp.content)
        logger.info(f"Downloaded Pixabay video: {output_path} ({Path(output_path).stat().st_size // 1024}KB)")
        return output_path

    async def trim_and_resize(
        self,
        input_path: str,
        output_path: str,
        duration: float = 2.5,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
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
            "-r", "30",
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

        logger.info(f"Trimmed Pixabay clip: {output_path} ({duration}s, {width}x{height})")
        return output_path

    async def fetch_clip(
        self,
        query: str,
        output_path: str,
        duration: float = 2.5,
        width: int = 1080,
        height: int = 1920,
        used_video_ids: set | None = None,
    ) -> tuple[str | None, str | None]:
        """Search, download, trim and resize a Pixabay clip.

        Returns (file_path, video_id) or (None, None).
        """
        try:
            trim_duration = duration + 3.0
            videos = await self.search_videos(query)
            if not videos:
                logger.warning(f"No Pixabay results for '{query}'")
                return None, None

            for video in videos:
                video_id = video.get("id")
                vid_str = f"pixabay_{video_id}" if video_id else None
                if used_video_ids is not None and vid_str in used_video_ids:
                    continue

                best_url = self._pick_best_file(video)
                if not best_url:
                    continue

                raw_path = str(Path(output_path).parent / f"raw_{Path(output_path).name}")
                await self.download_video(best_url, raw_path)
                result = await self.trim_and_resize(raw_path, output_path, trim_duration, width, height)
                Path(raw_path).unlink(missing_ok=True)

                if used_video_ids is not None and vid_str:
                    used_video_ids.add(vid_str)
                return result, vid_str

            logger.warning(f"No suitable Pixabay video for '{query}'")
            return None, None

        except Exception as e:
            logger.error(f"Pixabay fetch failed for '{query}': {e}")
            return None, None


_pixabay_service: PixabayService | None = None


def get_pixabay_service() -> PixabayService | None:
    global _pixabay_service
    if _pixabay_service is None:
        if not settings.pixabay_api_key:
            return None
        try:
            _pixabay_service = PixabayService()
        except ValueError:
            return None
    return _pixabay_service
