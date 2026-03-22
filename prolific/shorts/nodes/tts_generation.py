"""TTS generation node - narrates the script with energetic 11Labs voice."""

import asyncio
import logging
import shutil
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
    story_plan = state.get("story_plan")

    if not script and not story_plan:
        return {"errors": ["No script or story plan for TTS"], "current_phase": "failed"}

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

    if story_plan and story_plan.segments:
        return await _generate_segmented_tts(tts, story_plan, output_dir, script)

    output_path = str(output_dir / "narration.mp3")
    duration = await tts.synthesize_text(script.full_text, output_path)
    logger.info(f"Narration generated: {output_path} (~{duration:.1f}s)")

    return {
        "audio_path": output_path,
        "audio_duration_seconds": duration,
        "current_phase": "video_assembly",
        "messages": [AIMessage(content=f"Narration: {duration:.1f}s")],
    }


async def _generate_segmented_tts(tts, story_plan, output_dir: Path, script) -> dict:
    """Generate per-segment TTS for narrate/narrate_over segments, then concat."""
    narration_segments = [
        seg for seg in story_plan.segments
        if seg.narration_text and seg.mode in ("narrate", "narrate_over")
    ]

    if not narration_segments:
        logger.warning("Story plan has no narration segments — nothing to synthesize")
        return {"errors": ["No narration text in story plan"], "current_phase": "failed"}

    logger.info(f"Generating TTS for {len(narration_segments)} narration segments")

    segment_paths = []
    for i, seg in enumerate(narration_segments):
        seg_path = str(output_dir / f"narration_seg_{i:02d}.mp3")
        try:
            duration = await tts.synthesize_text(seg.narration_text, seg_path)
            segment_paths.append(seg_path)
            logger.info(
                f"  Seg {i} ({seg.mode}): {duration:.1f}s "
                f"\"{seg.narration_text[:50]}...\""
            )
        except Exception as e:
            logger.error(f"  Seg {i} TTS failed: {e}")
            return {"errors": [f"TTS failed for segment {i}: {e}"], "current_phase": "failed"}

    combined_path = str(output_dir / "narration.mp3")
    total_duration = await _concat_audio_files(segment_paths, combined_path)
    logger.info(f"Combined narration: {combined_path} ({total_duration:.1f}s)")

    return {
        "audio_path": combined_path,
        "audio_duration_seconds": total_duration,
        "audio_segment_paths": segment_paths,
        "current_phase": "video_assembly",
        "messages": [AIMessage(content=f"Narration: {total_duration:.1f}s ({len(segment_paths)} segments)")],
    }


async def _concat_audio_files(paths: list[str], output_path: str) -> float:
    """Concatenate audio files using ffmpeg concat demuxer. Returns total duration."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    if len(paths) == 1:
        import shutil as sh
        sh.copy2(paths[0], output_path)
        return await _get_audio_duration(paths[0])

    concat_file = str(Path(output_path).parent / "concat_narration.txt")
    with open(concat_file, "w") as f:
        for p in paths:
            f.write(f"file '{Path(p).resolve()}'\n")

    cmd = [
        ffmpeg, "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c:a", "copy", "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    Path(concat_file).unlink(missing_ok=True)

    if proc.returncode != 0:
        raise RuntimeError(f"Audio concat failed: {stderr.decode()[-300:]}")

    return await _get_audio_duration(output_path)


async def _get_audio_duration(path: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0
