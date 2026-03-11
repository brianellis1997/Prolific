"""TTS generation node - converts script to audio via 11Labs."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.youtube.schemas import AudioChunk
from prolific.youtube.services.tts import get_tts_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def tts_generation_node(state: YouTubePipelineState) -> dict:
    """Generate audio for each script section and stitch together."""
    logger.info("=== TTS GENERATION ===")

    sections = state["script_sections"]
    thread_id = state["thread_id"]
    output_dir = Path(settings.youtube_output_dir) / thread_id / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    tts_service = get_tts_service()
    audio_chunks = []
    section_audio_paths = []
    total_duration = 0.0

    for i, section in enumerate(sections):
        if not section.content:
            logger.warning(f"  Section {section.section_number} has no content, skipping")
            continue

        logger.info(f"  [{i + 1}/{len(sections)}] Synthesizing section {section.section_number}: "
                     f"{section.title} ({section.word_count} words)")

        section_dir = str(output_dir / f"section_{section.section_number:02d}")
        chunk_results = await tts_service.synthesize_long_text(
            text=section.content,
            output_dir=section_dir,
            prefix=f"s{section.section_number:02d}",
        )

        chunk_paths = [path for path, _ in chunk_results]
        section_audio_path = str(output_dir / f"section_{section.section_number:02d}.mp3")
        section_duration = await tts_service.stitch_audio(chunk_paths, section_audio_path)

        total_duration += section_duration
        section_audio_paths.append(section_audio_path)

        audio_chunk = AudioChunk(
            section_number=section.section_number,
            text=section.content[:100] + "...",
            audio_path=section_audio_path,
            duration_seconds=section_duration,
        )
        audio_chunks.append(audio_chunk)

        logger.info(f"    Section {section.section_number}: {section_duration:.0f}s")

    final_audio_path = str(output_dir / "full_narration.mp3")
    if section_audio_paths:
        total_duration = await tts_service.stitch_audio(section_audio_paths, final_audio_path)

    hours = total_duration / 3600
    logger.info(f"TTS complete: {total_duration:.0f}s ({hours:.1f} hours)")

    return {
        "audio_chunks": audio_chunks,
        "final_audio_path": final_audio_path,
        "current_phase": "video_assembly",
        "messages": [AIMessage(content=f"Audio generated: {hours:.1f} hours")],
    }
