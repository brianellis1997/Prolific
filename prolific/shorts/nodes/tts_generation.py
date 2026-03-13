"""TTS generation node - narrates the script with energetic 11Labs voice."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.services.tts import TTSService
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def tts_generation_node(state: ShortsPipelineState) -> dict:
    """Generate TTS narration for the short script."""
    logger.info("=== SHORTS: TTS GENERATION ===")

    script = state.get("script")
    if not script:
        return {"errors": ["No script for TTS"], "current_phase": "failed"}

    voice_id = settings.elevenlabs_shorts_voice_id or settings.elevenlabs_voice_id
    if not voice_id:
        return {"errors": ["No voice ID configured for shorts"], "current_phase": "failed"}

    tts = TTSService(
        voice_id=voice_id,
        stability=settings.elevenlabs_shorts_stability,
        similarity_boost=settings.elevenlabs_shorts_similarity_boost,
        style=settings.elevenlabs_shorts_style,
    )

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / "narration.mp3")

    duration = await tts.synthesize_text(script.full_text, output_path)
    logger.info(f"Narration generated: {output_path} (~{duration:.1f}s)")

    return {
        "audio_path": output_path,
        "audio_duration_seconds": duration,
        "current_phase": "video_assembly",
        "messages": [AIMessage(content=f"Narration: {duration:.1f}s")],
    }
