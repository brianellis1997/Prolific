"""Video assembly service using ffmpeg for Ken Burns effect and stitching."""

import asyncio
import logging
import shutil
from pathlib import Path

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class VideoAssemblyService:
    def __init__(self, output_dir: str | None = None):
        self.output_dir = output_dir or settings.youtube_output_dir
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH. Install ffmpeg first.")

    async def _run_ffmpeg(self, args: list[str], description: str = "") -> None:
        """Run ffmpeg as async subprocess."""
        cmd = [self.ffmpeg] + args
        logger.debug(f"ffmpeg: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode()[-500:] if stderr else "unknown error"
            raise RuntimeError(f"ffmpeg failed ({description}): {error_msg}")

    async def create_ken_burns_clip(
        self,
        image_path: str,
        duration: float,
        output_path: str,
        direction: str = "zoom_in",
        fps: int = 30,
        fade_in: float = 0.0,
        width: int = 1920,
        height: int = 1080,
    ) -> str:
        """Create a Ken Burns clip from a single image."""
        total_frames = int(duration * fps)
        resolution = f"{width}x{height}"

        zoom_filters = {
            "zoom_in": f"zoompan=z='min(zoom+0.0001,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}",
            "zoom_out": f"zoompan=z='if(eq(on,0),1.3,max(zoom-0.0001,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}",
            "pan_left": f"zoompan=z='1.1':x='iw*0.1+on/(on+1)*iw*0.1':y='ih/2-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}",
            "pan_right": f"zoompan=z='1.1':x='iw*0.3-on/(on+1)*iw*0.1':y='ih/2-(ih/zoom/2)':d={total_frames}:s={resolution}:fps={fps}",
        }

        vf = zoom_filters.get(direction, zoom_filters["zoom_in"])
        if fade_in > 0:
            fade_frames = int(fade_in * fps)
            vf += f",fade=t=in:st=0:d={fade_in}"

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        await self._run_ffmpeg(
            [
                "-loop", "1",
                "-i", image_path,
                "-vf", vf,
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-y",
                output_path,
            ],
            description=f"Ken Burns {direction} ({duration:.0f}s)",
        )

        logger.info(f"Ken Burns clip: {output_path} ({duration:.0f}s, {direction})")
        return output_path

    async def _get_duration(self, path: str) -> float:
        """Get video duration using ffprobe."""
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return 0.0
        proc = await asyncio.create_subprocess_exec(
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        try:
            return float(stdout.decode().strip())
        except (ValueError, AttributeError):
            return 0.0

    async def _crossfade_clips(
        self,
        clip_paths: list[str],
        output_path: str,
        crossfade_duration: float = 2.0,
    ) -> None:
        """Concatenate clips with xfade crossfade transitions."""
        if len(clip_paths) == 1:
            await self._run_ffmpeg(
                ["-i", clip_paths[0], "-c", "copy", "-y", output_path],
                description="copy single clip",
            )
            return

        durations = []
        for p in clip_paths:
            d = await self._get_duration(p)
            durations.append(d if d > 0 else 2.5)

        min_duration = min(durations)
        cf = min(crossfade_duration, min_duration * 0.4)
        if cf < 0.1:
            cf = 0.0

        if cf == 0.0:
            concat_list = "\n".join(f"file '{Path(p).resolve()}'" for p in clip_paths)
            concat_file = str(Path(output_path).parent / "concat_list.txt")
            Path(concat_file).write_text(concat_list)
            await self._run_ffmpeg(
                ["-f", "concat", "-safe", "0", "-i", concat_file,
                 "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                 "-pix_fmt", "yuv420p", "-y", output_path],
                description=f"concat {len(clip_paths)} clips (no crossfade)",
            )
            Path(concat_file).unlink(missing_ok=True)
            logger.info(f"Concatenated {len(clip_paths)} clips -> {output_path}")
            return

        inputs = []
        for p in clip_paths:
            inputs.extend(["-i", p])

        n = len(clip_paths)
        filter_parts = []

        offset = max(0.1, durations[0] - cf)
        filter_parts.append(
            f"[0:v][1:v]xfade=transition=fade:duration={cf}:offset={offset}[v1]"
        )

        for i in range(2, n):
            prev_label = f"v{i - 1}"
            out_label = f"v{i}"
            offset += max(0.1, durations[i - 1] - cf)
            filter_parts.append(
                f"[{prev_label}][{i}:v]xfade=transition=fade:duration={cf}:offset={offset}[{out_label}]"
            )

        final_label = f"v{n - 1}"
        filter_complex = ";".join(filter_parts)

        await self._run_ffmpeg(
            inputs + [
                "-filter_complex", filter_complex,
                "-map", f"[{final_label}]",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-y",
                output_path,
            ],
            description=f"crossfade {n} clips",
        )
        logger.info(f"Crossfaded {n} clips -> {output_path}")

    async def assemble_video(
        self,
        clip_paths: list[str],
        audio_path: str,
        output_path: str,
        crossfade_duration: float = 2.0,
    ) -> str:
        """Assemble video clips with crossfade transitions and audio overlay."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        if len(clip_paths) == 1:
            await self._run_ffmpeg(
                [
                    "-i", clip_paths[0],
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    "-y",
                    output_path,
                ],
                description="single clip + audio",
            )
            return output_path

        if crossfade_duration == 0:
            concat_list = "\n".join(f"file '{Path(p).resolve()}'" for p in clip_paths)
            concat_file = str(Path(output_path).parent / "concat_list.txt")
            Path(concat_file).write_text(concat_list)
            await self._run_ffmpeg(
                [
                    "-f", "concat", "-safe", "0", "-i", concat_file,
                    "-i", audio_path,
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    "-y", output_path,
                ],
                description=f"concat {len(clip_paths)} clips + audio",
            )
            Path(concat_file).unlink(missing_ok=True)
            file_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
            logger.info(f"Final video: {output_path} ({file_size_mb:.0f} MB)")
            return output_path

        concat_video = str(Path(output_path).parent / "concat_video.mp4")
        await self._crossfade_clips(clip_paths, concat_video, crossfade_duration)

        await self._run_ffmpeg(
            [
                "-i", concat_video,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-shortest",
                "-y",
                output_path,
            ],
            description="add audio overlay",
        )

        Path(concat_video).unlink(missing_ok=True)

        file_size_mb = Path(output_path).stat().st_size / (1024 * 1024)
        logger.info(f"Final video: {output_path} ({file_size_mb:.0f} MB)")
        return output_path


_video_service: VideoAssemblyService | None = None


def get_video_assembly_service() -> VideoAssemblyService:
    global _video_service
    if _video_service is None:
        _video_service = VideoAssemblyService()
    return _video_service
