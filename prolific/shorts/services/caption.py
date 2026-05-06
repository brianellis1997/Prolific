"""Caption generation service using Whisper + ASS subtitles + ffmpeg burn-in."""

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

from prolific.core.config import settings
from prolific.shorts.schemas import CaptionSegment

logger = logging.getLogger(__name__)


class CaptionService:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.openai_api_key
        self.ffmpeg = shutil.which("ffmpeg")

    async def generate_word_timestamps(self, audio_path: str) -> list[CaptionSegment]:
        """Get word-level timestamps from audio using OpenAI Whisper API."""
        async with httpx.AsyncClient(timeout=60.0) as client:
            with open(audio_path, "rb") as f:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data={
                        "model": "whisper-1",
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "word",
                    },
                    files={"file": ("audio.mp3", f, "audio/mpeg")},
                )
                resp.raise_for_status()
                data = resp.json()

        segments = []
        for word_info in data.get("words", []):
            segments.append(CaptionSegment(
                word=word_info["word"],
                start_time=word_info["start"],
                end_time=word_info["end"],
            ))

        logger.info(f"Generated {len(segments)} word timestamps from {audio_path}")
        return segments

    def generate_ass_subtitles(
        self,
        segments: list[CaptionSegment],
        output_path: str,
        words_per_group: int | None = None,
        font_size: int | None = None,
        video_width: int = 1080,
        video_height: int = 1920,
    ) -> str:
        """Generate ASS subtitle file from word segments."""
        if words_per_group is None:
            words_per_group = settings.shorts_caption_words_per_group
        if font_size is None:
            font_size = settings.shorts_caption_font_size

        margin_bottom = int(video_height * 0.25)

        header = f"""[Script Info]
Title: Shorts Captions
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,40,40,{margin_bottom},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events = []
        for i in range(0, len(segments), words_per_group):
            group = segments[i : i + words_per_group]
            if not group:
                continue

            start_time = group[0].start_time
            end_time = group[-1].end_time
            text = " ".join(seg.word for seg in group).strip().upper()

            start_str = self._seconds_to_ass_time(start_time)
            end_str = self._seconds_to_ass_time(end_time)

            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{text}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(header + "\n".join(events), encoding="utf-8")

        logger.info(f"Generated ASS subtitles: {output_path} ({len(events)} groups)")
        return output_path

    async def burn_captions(
        self,
        video_path: str,
        subtitle_path: str,
        output_path: str,
    ) -> str:
        """Burn ASS subtitles into video using ffmpeg."""
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found in PATH")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="prolific_cap_")
        tmp_sub = Path(tmp_dir) / "captions.ass"
        shutil.copy2(subtitle_path, str(tmp_sub))

        cmd = [
            self.ffmpeg,
            "-i", video_path,
            "-vf", f"ass={tmp_sub}",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-c:a", "copy",
            "-y",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        shutil.rmtree(tmp_dir, ignore_errors=True)

        if proc.returncode != 0:
            error_msg = stderr.decode()[-500:] if stderr else "unknown error"
            raise RuntimeError(f"ffmpeg caption burn-in failed: {error_msg}")

        logger.info(f"Burned captions into {output_path}")
        return output_path

    @staticmethod
    def _seconds_to_ass_time(seconds: float) -> str:
        """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds % 1) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def generate_srt_subtitles(
        self,
        segments: list[CaptionSegment],
        output_path: str,
        words_per_group: int | None = None,
    ) -> str:
        """Generate SRT subtitle file from word segments.

        Uploaded to YouTube via captions.insert after the video upload — this
        suppresses YT's auto-generated CC (which renders in a small black box
        at the top of the frame and visually conflicts with our burned-in ASS
        captions at the bottom). Same word grouping as the ASS generator so
        viewers see the same text whether they have CC on or off.
        """
        if words_per_group is None:
            words_per_group = settings.shorts_caption_words_per_group

        events = []
        for i in range(0, len(segments), words_per_group):
            group = segments[i : i + words_per_group]
            if not group:
                continue
            start = self._seconds_to_srt_time(group[0].start_time)
            end = self._seconds_to_srt_time(group[-1].end_time)
            text = " ".join(seg.word for seg in group).strip().upper()
            events.append(f"{i // words_per_group + 1}\n{start} --> {end}\n{text}\n")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text("\n".join(events), encoding="utf-8")
        logger.info(f"Generated SRT subtitles: {output_path} ({len(events)} cues)")
        return output_path

    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


_caption_service: CaptionService | None = None


def get_caption_service() -> CaptionService:
    global _caption_service
    if _caption_service is None:
        _caption_service = CaptionService()
    return _caption_service
