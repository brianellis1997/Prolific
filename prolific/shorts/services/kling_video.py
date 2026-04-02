"""Kling AI video generation service via FAL.ai."""

import asyncio
import logging
import os
import shutil
from pathlib import Path

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class KlingVideoService:
    def __init__(self):
        self.fal_api_key = settings.fal_api_key
        os.environ["FAL_KEY"] = self.fal_api_key
        self.image_to_video_endpoint = settings.kling_image_to_video_endpoint
        self.text_to_video_endpoint = settings.kling_model_endpoint
        self.default_duration = settings.kling_video_duration
        self.cost_per_sec = settings.kling_cost_per_sec_usd
        self.ffmpeg = shutil.which("ffmpeg")

        self._ref_local_paths: dict[str, list[str]] = {}
        if settings.kling_marble_ref_urls:
            self._ref_local_paths["marble"] = [
                p.strip() for p in settings.kling_marble_ref_urls.split(",") if p.strip()
            ]
        if settings.kling_worm_ref_urls:
            self._ref_local_paths["worm"] = [
                p.strip() for p in settings.kling_worm_ref_urls.split(",") if p.strip()
            ]

        self._uploaded_refs: dict[str, dict] = {}

        logger.info(
            f"KlingVideoService initialized: "
            f"characters={list(self._ref_local_paths.keys())}, "
            f"endpoint={self.image_to_video_endpoint}"
        )

    async def _get_uploaded_refs(self, character: str) -> dict | None:
        """Upload reference images for a character and cache the URLs."""
        if character in self._uploaded_refs:
            return self._uploaded_refs[character]

        paths = self._ref_local_paths.get(character, [])
        if not paths:
            return None

        existing = [p for p in paths if Path(p).exists()]
        if not existing:
            return None

        import fal_client
        urls = []
        for p in existing:
            url = await fal_client.upload_file_async(p)
            urls.append(url)
            logger.info(f"Uploaded {character} ref: {Path(p).name} -> {url[:60]}...")

        refs = {
            "frontal_url": urls[0],
            "reference_urls": urls[1:] if len(urls) > 1 else [],
            "start_url": urls[0],
        }
        self._uploaded_refs[character] = refs
        return refs

    async def generate_video(
        self,
        prompt: str,
        output_path: str,
        character: str = "marble",
        duration: str | None = None,
    ) -> str | None:
        """Generate a video clip via Kling v3 image-to-video with Elements for character consistency.

        Uses Elements (frontal + reference images) to lock character appearance,
        plus start_image_url as the scene starting frame.
        Falls back to text-to-video if no references available.
        """
        import fal_client

        duration = duration or self.default_duration
        dur_int = max(3, min(15, int(float(duration))))
        duration = str(dur_int)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        refs = await self._get_uploaded_refs(character)

        try:
            if refs:
                elements = [{
                    "type": "image_set",
                    "frontal_image_url": refs["frontal_url"],
                    "reference_image_urls": refs["reference_urls"] or [refs["frontal_url"]],
                }]

                logger.info(
                    f"Kling v3 Elements: character={character}, "
                    f"duration={duration}s, prompt={prompt[:80]}..."
                )
                result = await fal_client.run_async(
                    self.image_to_video_endpoint,
                    arguments={
                        "prompt": f"@Element1 {prompt}",
                        "start_image_url": refs["start_url"],
                        "elements": elements,
                        "duration": duration,
                        "aspect_ratio": "9:16",
                        "generate_audio": False,
                    },
                )
            else:
                logger.info(
                    f"Kling text-to-video (no refs): character={character}, "
                    f"duration={duration}s, prompt={prompt[:80]}..."
                )
                result = await fal_client.run_async(
                    self.text_to_video_endpoint,
                    arguments={
                        "prompt": prompt,
                        "duration": duration,
                        "aspect_ratio": "9:16",
                    },
                )

            video_url = result.get("video", {}).get("url")
            if not video_url:
                logger.warning(f"Kling returned no video URL. Keys: {list(result.keys())}")
                return None

            raw_path = str(Path(output_path).with_suffix(".raw.mp4"))
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.get(video_url)
                resp.raise_for_status()
                Path(raw_path).write_bytes(resp.content)
                size_kb = len(resp.content) // 1024
                logger.info(f"Downloaded Kling video: {raw_path} ({size_kb}KB)")

            await self._normalize_video(raw_path, output_path)

            cost = float(duration) * self.cost_per_sec
            logger.info(f"Kling generation complete: {output_path} ({duration}s, ${cost:.3f})")

            Path(raw_path).unlink(missing_ok=True)
            return output_path

        except Exception as e:
            logger.error(f"Kling generation failed: {e}")
            return None

    async def _normalize_video(
        self,
        input_path: str,
        output_path: str,
        width: int = 1080,
        height: int = 1920,
    ):
        """Normalize video to 1080x1920 portrait, 30fps, no audio."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH")

        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )

        cmd = [
            self.ffmpeg,
            "-i", input_path,
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
            raise RuntimeError(f"ffmpeg normalize failed: {error_msg}")

        logger.info(f"Normalized video: {output_path} ({width}x{height}, 30fps)")


_kling_service: KlingVideoService | None = None


def get_kling_service() -> KlingVideoService:
    global _kling_service
    if _kling_service is None:
        _kling_service = KlingVideoService()
    return _kling_service
