"""yt-dlp wrapper for downloading clips from YouTube/Twitch/Reddit."""

import asyncio
import logging
import shutil
from pathlib import Path

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class ClipDownloader:
    def __init__(self):
        self.ffmpeg = shutil.which("ffmpeg")
        self.yt_dlp = shutil.which("yt-dlp") or _find_venv_binary("yt-dlp")
        if not self.yt_dlp:
            raise RuntimeError("yt-dlp not found. Install with: pip install yt-dlp")

    async def get_clip_info(self, url: str) -> dict | None:
        """Get clip metadata without downloading."""
        cmd = [
            self.yt_dlp,
            "--dump-json",
            "--no-download",
            "--no-warnings",
            url,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                logger.warning(f"yt-dlp info failed for {url}: {stderr.decode()[-300:]}")
                return None

            import json
            info = json.loads(stdout.decode())
            return {
                "title": info.get("title", ""),
                "uploader": info.get("uploader", info.get("channel", "")),
                "duration": info.get("duration", 0),
                "view_count": info.get("view_count", 0),
                "url": url,
                "platform": _detect_platform(url),
            }
        except asyncio.TimeoutError:
            logger.warning(f"yt-dlp info timed out for {url}")
            return None
        except Exception as e:
            logger.warning(f"yt-dlp info error for {url}: {e}")
            return None

    async def _extract_audio(self, input_path: str, output_path: str) -> None:
        """Extract audio track from a video file to AAC."""
        if not self.ffmpeg:
            return
        cmd = [
            self.ffmpeg, "-i", input_path,
            "-vn", "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-y", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"Audio extraction failed: {stderr.decode()[-200:]}")

    async def download_clip(
        self,
        url: str,
        output_dir: str,
        filename: str = "clip",
        max_duration: int = 60,
    ) -> tuple[str, str] | None:
        """Download a clip and convert to 1080x1920 portrait (no audio).

        Returns (portrait_video_path, audio_path) or None on failure.
        The audio_path is the original clip audio for use in clip_plays mode.
        """
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)

        raw_path = str(output_dir_path / f"{filename}_raw.mp4")
        final_path = str(output_dir_path / f"{filename}.mp4")
        audio_path = str(output_dir_path / f"{filename}_audio.aac")

        is_hls = ".m3u8" in url or url.endswith(".m3u8")

        if is_hls and self.ffmpeg:
            cmd = [
                self.ffmpeg,
                "-i", url,
                "-t", str(max_duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-y", raw_path,
            ]
        else:
            cmd = [
                self.yt_dlp,
                "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
                "--merge-output-format", "mp4",
                "--no-playlist",
                "--no-warnings",
                "-o", raw_path,
                url,
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = 180 if is_hls else 120
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                label = "ffmpeg HLS" if is_hls else "yt-dlp"
                logger.error(f"{label} download failed: {stderr.decode()[-500:]}")
                return None

            if not Path(raw_path).exists():
                logger.error(f"Downloaded file not found at {raw_path}")
                return None

            await self._extract_audio(raw_path, audio_path)
            await self._convert_to_portrait(raw_path, final_path, max_duration)
            Path(raw_path).unlink(missing_ok=True)
            return final_path, audio_path if Path(audio_path).exists() else ""

        except asyncio.TimeoutError:
            logger.error(f"yt-dlp download timed out for {url}")
            return None
        except Exception as e:
            logger.error(f"Clip download failed for {url}: {e}")
            return None

    async def _convert_to_portrait(
        self,
        input_path: str,
        output_path: str,
        max_duration: int = 60,
        width: int = 1080,
        height: int = 1920,
    ) -> str:
        """Convert clip to 9:16 portrait with blurred background, no audio, 30fps."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH")

        vf = (
            f"split[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=30[blurred];"
            f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[scaled];"
            f"[blurred][scaled]overlay=(W-w)/2:(H-h)/2"
        )

        cmd = [
            self.ffmpeg,
            "-i", input_path,
            "-t", str(max_duration),
            "-filter_complex", vf,
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
            error_msg = stderr.decode()[-500:] if stderr else "unknown"
            raise RuntimeError(f"Portrait conversion failed: {error_msg}")

        logger.info(f"Converted to portrait: {output_path}")
        return output_path

    async def search_and_download(
        self,
        query: str,
        output_dir: str,
        filename: str = "clip",
        max_results: int = 5,
        max_duration: int = 60,
    ) -> tuple[str | None, dict | None]:
        """Search YouTube via yt-dlp and download the best result.
        Returns (file_path, info_dict) or (None, None)."""
        search_query = f"ytsearch{max_results}:{query}"
        cmd = [
            self.yt_dlp,
            "--dump-json",
            "--no-download",
            "--no-warnings",
            "--flat-playlist",
            search_query,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0 or not stdout:
                return None, None

            import json
            results = []
            for line in stdout.decode().strip().split("\n"):
                if line.strip():
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

            results.sort(key=lambda r: r.get("view_count", 0) or 0, reverse=True)

            for result in results:
                duration = result.get("duration", 0) or 0
                if duration > 0 and duration <= max_duration * 2:
                    video_url = result.get("url") or f"https://www.youtube.com/watch?v={result.get('id', '')}"
                    dl_result = await self.download_clip(video_url, output_dir, filename, max_duration)
                    if dl_result:
                        clip_path, _ = dl_result
                        info = {
                            "title": result.get("title", ""),
                            "uploader": result.get("uploader", result.get("channel", "")),
                            "duration": duration,
                            "view_count": result.get("view_count", 0),
                            "url": video_url,
                            "platform": "youtube",
                        }
                        return clip_path, info

            return None, None

        except asyncio.TimeoutError:
            logger.warning(f"yt-dlp search timed out for '{query}'")
            return None, None
        except Exception as e:
            logger.warning(f"yt-dlp search error for '{query}': {e}")
            return None, None


def _find_venv_binary(name: str) -> str | None:
    """Find a binary in the current Python's venv bin directory."""
    import sys
    venv_bin = Path(sys.executable).parent / name
    if venv_bin.exists():
        return str(venv_bin)
    return None


def _detect_platform(url: str) -> str:
    url_lower = url.lower()
    if "twitch" in url_lower:
        return "twitch"
    elif "kick.com" in url_lower:
        return "kick"
    elif "youtube" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "reddit" in url_lower:
        return "reddit"
    return "other"


_clip_downloader: ClipDownloader | None = None


def get_clip_downloader() -> ClipDownloader:
    global _clip_downloader
    if _clip_downloader is None:
        _clip_downloader = ClipDownloader()
    return _clip_downloader
