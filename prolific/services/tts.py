"""Text-to-speech service using 11Labs API."""

import logging
import struct
import wave
from pathlib import Path

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)

CHUNK_SIZE = 4500
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"


class TTSService:
    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str | None = None,
        stability: float = 0.65,
        similarity_boost: float = 0.75,
        style: float = 0.2,
        use_speaker_boost: bool = True,
    ):
        self.api_key = api_key or settings.elevenlabs_api_key
        self.voice_id = voice_id or settings.elevenlabs_voice_id
        self.model_id = model_id or settings.elevenlabs_model_id
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.style = style
        self.use_speaker_boost = use_speaker_boost

    async def synthesize_text(
        self,
        text: str,
        output_path: str,
        max_retries: int = 3,
        previous_text: str = "",
        next_text: str = "",
    ) -> float:
        """Synthesize text to MP3 file. Returns duration in seconds."""
        import asyncio

        last_error = None
        for attempt in range(max_retries):
            try:
                body = {
                    "text": text,
                    "model_id": self.model_id,
                    "voice_settings": {
                        "stability": self.stability,
                        "similarity_boost": self.similarity_boost,
                        "style": self.style,
                        "use_speaker_boost": self.use_speaker_boost,
                    },
                }
                if previous_text:
                    body["previous_text"] = previous_text[-1000:]
                if next_text:
                    body["next_text"] = next_text[:1000]

                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{ELEVENLABS_BASE_URL}/text-to-speech/{self.voice_id}",
                        headers={
                            "xi-api-key": self.api_key,
                            "Content-Type": "application/json",
                        },
                        json=body,
                    )
                    response.raise_for_status()

                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    Path(output_path).write_bytes(response.content)

                duration = self._estimate_mp3_duration(output_path)
                logger.info(f"Synthesized {len(text)} chars -> {output_path} (~{duration:.0f}s)")
                return duration

            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as e:
                last_error = e
                status = getattr(getattr(e, 'response', None), 'status_code', '?')
                if attempt < max_retries - 1:
                    wait = (attempt + 1) * 10
                    logger.warning(f"TTS attempt {attempt+1} failed (status={status}), retrying in {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"TTS failed after {max_retries} attempts: {e}")

        raise last_error

    async def synthesize_long_text(
        self,
        text: str,
        output_dir: str,
        prefix: str = "chunk",
    ) -> list[tuple[str, float]]:
        """Split long text into chunks, synthesize each with context continuity."""
        chunks = self._split_text(text, CHUNK_SIZE)
        results = []

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for i, chunk in enumerate(chunks):
            output_path = str(Path(output_dir) / f"{prefix}_{i:04d}.mp3")
            prev = chunks[i - 1] if i > 0 else ""
            nxt = chunks[i + 1] if i < len(chunks) - 1 else ""
            duration = await self.synthesize_text(
                chunk, output_path,
                previous_text=prev, next_text=nxt,
            )
            results.append((output_path, duration))

        return results

    async def stitch_audio(self, audio_paths: list[str], output_path: str) -> float:
        """Concatenate MP3 files with volume normalization. Returns total duration."""
        from pydub import AudioSegment

        target_dbfs = -18.0
        combined = AudioSegment.empty()
        for path in audio_paths:
            segment = AudioSegment.from_mp3(path)
            if segment.dBFS != float('-inf') and segment.dBFS != 0:
                change = target_dbfs - segment.dBFS
                segment = segment.apply_gain(change)
            combined += segment

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        combined.export(output_path, format="mp3")

        total_duration = len(combined) / 1000.0
        logger.info(f"Stitched {len(audio_paths)} files -> {output_path} ({total_duration:.0f}s, normalized to {target_dbfs}dBFS)")
        return total_duration

    @staticmethod
    def _split_text(text: str, max_chars: int) -> list[str]:
        """Split text at sentence boundaries, avoiding splits inside SSML tags."""
        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= max_chars:
                chunks.append(remaining)
                break

            split_pos = remaining[:max_chars].rfind(". ")
            if split_pos == -1:
                split_pos = remaining[:max_chars].rfind(".\n")
            if split_pos == -1:
                split_pos = remaining[:max_chars].rfind(" ")
            if split_pos == -1:
                split_pos = max_chars

            candidate = remaining[: split_pos + 1]
            open_tag = candidate.rfind("<")
            close_tag = candidate.rfind(">")
            if open_tag > close_tag:
                safe_pos = remaining[:open_tag].rfind(". ")
                if safe_pos == -1:
                    safe_pos = remaining[:open_tag].rfind(" ")
                if safe_pos > 0:
                    split_pos = safe_pos

            chunks.append(remaining[: split_pos + 1].strip())
            remaining = remaining[split_pos + 1 :].strip()

        return chunks

    @staticmethod
    def _estimate_mp3_duration(path: str) -> float:
        """Rough estimate of MP3 duration from file size. Assumes ~128kbps."""
        file_size = Path(path).stat().st_size
        return file_size / (128 * 1000 / 8)


_tts_service: TTSService | None = None


def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
