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
        page: int = 1,
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
                    "page": page,
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

        logger.info(f"Trimmed clip: {output_path} ({duration}s, {width}x{height})")
        return output_path

    def get_candidates(
        self,
        videos: list[dict],
        used_video_ids: set | None = None,
    ) -> list[dict]:
        """Filter search results into usable candidates with thumbnail info."""
        candidates = []
        for video in videos:
            video_id = video.get("id")
            vid_str = str(video_id) if video_id else None
            if used_video_ids is not None and vid_str in used_video_ids:
                continue
            best_file = self._pick_best_file(video)
            if not best_file:
                continue
            thumbnail = video.get("image", "")
            preview_pics = [p.get("picture", "") for p in video.get("video_pictures", [])[:3]]
            candidates.append({
                "video_id": vid_str,
                "best_file": best_file,
                "thumbnail_url": thumbnail,
                "preview_urls": preview_pics,
            })
        return candidates

    async def download_and_trim(
        self,
        candidate: dict,
        output_path: str,
        duration: float,
        width: int = 1080,
        height: int = 1920,
        used_video_ids: set | None = None,
    ) -> tuple[str | None, str | None]:
        """Download and trim a specific candidate. Returns (path, video_id)."""
        try:
            trim_duration = duration + 3.0
            raw_path = str(Path(output_path).parent / f"raw_{Path(output_path).name}")
            await self.download_video(candidate["best_file"]["link"], raw_path)
            result = await self.trim_and_resize(raw_path, output_path, trim_duration, width, height)
            Path(raw_path).unlink(missing_ok=True)
            vid_str = candidate["video_id"]
            if used_video_ids is not None and vid_str:
                used_video_ids.add(vid_str)
            return result, vid_str
        except Exception as e:
            logger.error(f"Download/trim failed: {e}")
            return None, None

    async def fetch_clip(
        self,
        query: str,
        output_path: str,
        duration: float = 2.5,
        width: int = 1080,
        height: int = 1920,
        used_video_ids: set | None = None,
        max_pages: int = 3,
    ) -> tuple[str | None, str | None]:
        """Search, download, trim and resize a stock clip.

        Returns (file_path, video_id) or (None, None).
        Pass used_video_ids to avoid fetching the same Pexels video twice.
        Paginates up to max_pages when all results on a page are already used.
        Falls back to progressively broader queries if specific ones return nothing.
        """
        try:
            trim_duration = duration + 3.0

            queries_to_try = [query]
            words = query.split()
            if len(words) > 3:
                queries_to_try.append(" ".join(words[:3]))
            if len(words) > 2:
                queries_to_try.append(" ".join(words[:2]))

            for q in queries_to_try:
                for page in range(1, max_pages + 1):
                    videos = await self.search_videos(q, page=page)
                    if not videos:
                        if page == 1:
                            logger.info(f"No Pexels results for '{q}', trying broader query")
                        break

                    all_used = True
                    for video in videos:
                        video_id = video.get("id")
                        vid_str = str(video_id) if video_id else None
                        if used_video_ids is not None and vid_str in used_video_ids:
                            continue
                        all_used = False

                        best_file = self._pick_best_file(video)
                        if not best_file:
                            continue

                        raw_path = str(Path(output_path).parent / f"raw_{Path(output_path).name}")
                        await self.download_video(best_file["link"], raw_path)
                        result = await self.trim_and_resize(raw_path, output_path, trim_duration, width, height)
                        Path(raw_path).unlink(missing_ok=True)

                        if used_video_ids is not None and vid_str:
                            used_video_ids.add(vid_str)
                        return result, vid_str

                    if all_used:
                        logger.info(f"All Pexels page {page} results for '{q}' already used, trying next page")
                    else:
                        break

            logger.warning(f"No suitable video files for '{query}'")
            return None, None

        except Exception as e:
            logger.error(f"Pexels fetch failed for '{query}': {e}")
            return None, None


_pexels_service: PexelsService | None = None


def get_pexels_service() -> PexelsService:
    global _pexels_service
    if _pexels_service is None:
        _pexels_service = PexelsService()
    return _pexels_service
