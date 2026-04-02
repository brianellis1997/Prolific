"""Video assembly node - stitches clips + images + captions + audio."""

import asyncio
import logging
import shutil
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.services.video import VideoAssemblyService
from prolific.shorts.services.caption import get_caption_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


def _align_visuals_to_speech(
    visual_assets: list,
    caption_segments: list,
    audio_duration: float,
) -> None:
    """Align visual segment durations to speech timestamps using script_text matching."""
    if not caption_segments or not visual_assets:
        return

    words_with_times = []
    for seg in caption_segments:
        w = seg.word.strip().lower()
        w = "".join(c for c in w if c.isalnum() or c == "'")
        if w:
            words_with_times.append((w, seg.start_time, seg.end_time))

    if not words_with_times:
        return

    word_idx = 0
    total_words = len(words_with_times)

    assets_with_text = [a for a in visual_assets if a.script_text and a.file_path]
    if not assets_with_text:
        return

    for i, asset in enumerate(assets_with_text):
        segment_words = asset.script_text.strip().lower().split()
        segment_words = [
            "".join(c for c in w if c.isalnum() or c == "'")
            for w in segment_words
        ]
        segment_words = [w for w in segment_words if w]

        if not segment_words:
            continue

        best_start_idx = _find_best_match(words_with_times, segment_words, word_idx)
        if best_start_idx >= 0:
            start_time = words_with_times[best_start_idx][1]
            end_idx = min(best_start_idx + len(segment_words) - 1, total_words - 1)
            end_time = words_with_times[end_idx][2]
            word_idx = end_idx + 1

            duration = max(2.0, round(end_time - start_time + 0.3, 1))
            asset.duration_seconds = duration
            logger.info(
                f"  [{asset.sequence_number}] Aligned: {start_time:.1f}s-{end_time:.1f}s "
                f"({duration:.1f}s) '{asset.script_text[:40]}...'"
            )
        else:
            logger.warning(
                f"  [{asset.sequence_number}] Could not align: '{asset.script_text[:40]}...'"
            )

    total_visual = sum(a.duration_seconds for a in visual_assets if a.file_path)
    if audio_duration > 0 and total_visual > 0:
        scale = audio_duration / total_visual
        if abs(scale - 1.0) > 0.15:
            for a in visual_assets:
                if a.file_path:
                    a.duration_seconds = max(2.0, round(a.duration_seconds * scale, 1))
            logger.info(f"  Scaled durations by {scale:.2f}x to match {audio_duration:.1f}s audio")


def _distribute_by_word_count(
    visual_assets: list,
    caption_segments: list,
    audio_duration: float,
) -> None:
    """Distribute audio duration evenly across visual segments when no script_text mapping exists."""
    assets_with_files = [a for a in visual_assets if a.file_path]
    if not assets_with_files or not caption_segments or audio_duration <= 0:
        return

    n = len(assets_with_files)
    total_words = len(caption_segments)
    words_per_segment = max(1, total_words // n)

    word_idx = 0
    for i, asset in enumerate(assets_with_files):
        if i == n - 1:
            end_idx = total_words - 1
        else:
            end_idx = min(word_idx + words_per_segment - 1, total_words - 1)

        start_time = caption_segments[word_idx].start_time
        end_time = caption_segments[end_idx].end_time
        duration = max(2.0, round(end_time - start_time + 0.3, 1))
        asset.duration_seconds = duration

        word_idx = end_idx + 1
        if word_idx >= total_words:
            word_idx = total_words - 1

    logger.info(f"  Distributed {total_words} words across {n} segments by equal word count")


def _find_best_match(words_with_times: list, segment_words: list, start_from: int) -> int:
    """Find the best starting position in words_with_times for segment_words."""
    if not segment_words:
        return -1

    target = segment_words[0]
    search_range = min(start_from + 30, len(words_with_times))

    for i in range(start_from, search_range):
        if words_with_times[i][0] == target:
            matched = 0
            for j, sw in enumerate(segment_words[:5]):
                if i + j < len(words_with_times) and words_with_times[i + j][0] == sw:
                    matched += 1
            if matched >= min(3, len(segment_words)):
                return i

    for i in range(max(0, start_from - 10), start_from):
        if words_with_times[i][0] == target:
            return i

    return start_from if start_from < len(words_with_times) else -1


MAX_IMAGE_DURATION = 4.0
KB_DIRECTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right"]


def _split_long_segments(visual_assets: list) -> list:
    """Split image segments longer than MAX_IMAGE_DURATION into two with alternating Ken Burns."""
    from prolific.shorts.schemas import VisualAsset
    result = []
    for asset in visual_assets:
        if (
            asset.asset_type in ("web_image", "ai_image")
            and asset.file_path
            and asset.duration_seconds > MAX_IMAGE_DURATION
        ):
            half = round(asset.duration_seconds / 2, 1)
            current_idx = KB_DIRECTIONS.index(asset.ken_burns_direction) if asset.ken_burns_direction in KB_DIRECTIONS else 0
            alt_direction = KB_DIRECTIONS[(current_idx + 1) % len(KB_DIRECTIONS)]

            result.append(VisualAsset(
                sequence_number=asset.sequence_number,
                asset_type=asset.asset_type,
                search_query=asset.search_query,
                file_path=asset.file_path,
                width=asset.width,
                height=asset.height,
                duration_seconds=half,
                ken_burns_direction=asset.ken_burns_direction,
                script_text=asset.script_text,
            ))
            result.append(VisualAsset(
                sequence_number=asset.sequence_number + 100,
                asset_type=asset.asset_type,
                search_query=asset.search_query,
                file_path=asset.file_path,
                width=asset.width,
                height=asset.height,
                duration_seconds=half,
                ken_burns_direction=alt_direction,
                script_text="",
            ))
            logger.info(f"  Split segment [{asset.sequence_number}] ({asset.duration_seconds:.1f}s -> 2x{half:.1f}s)")
        else:
            result.append(asset)
    return result


async def _add_number_overlay(
    input_path: str, output_path: str, label: str, duration: float
) -> str:
    """Add a numbered text overlay to a clip for compilation-style shorts."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not label:
        shutil.copy2(input_path, output_path)
        return output_path

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"drawtext=text='{label}':"
        f"fontsize=120:fontcolor=white:borderw=4:bordercolor=black:"
        f"x=(w-text_w)/2:y=h*0.15"
    )
    cmd = [
        ffmpeg, "-i", input_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Number overlay failed, using original: {stderr.decode()[-200:]}")
        shutil.copy2(input_path, output_path)
    return output_path


async def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


async def _add_silent_audio(input_path: str, output_path: str, duration: float) -> str:
    """Add a silent audio track to a video that has no audio."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        shutil.copy2(input_path, output_path)
        return output_path
    cmd = [
        ffmpeg,
        "-i", input_path,
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        shutil.copy2(input_path, output_path)
    return output_path


async def _trim_clip_segment(
    input_path: str,
    output_path: str,
    start_seconds: float,
    duration_seconds: float,
    clip_audio_path: str = "",
) -> str:
    """Trim a source clip to a specific time range, re-muxing original audio.

    The portrait clip has no audio (-an), so we pull audio from clip_audio_path
    and mux it in, keeping clip video and audio perfectly in sync.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return input_path

    has_audio = clip_audio_path and Path(clip_audio_path).exists()

    if has_audio:
        cmd = [
            ffmpeg,
            "-ss", str(start_seconds), "-t", str(duration_seconds), "-i", input_path,
            "-ss", str(start_seconds), "-t", str(duration_seconds), "-i", clip_audio_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-map", "0:v", "-map", "1:a",
            "-y", output_path,
        ]
    else:
        cmd = [
            ffmpeg,
            "-ss", str(start_seconds), "-t", str(duration_seconds), "-i", input_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-an", "-y", output_path,
        ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Clip trim failed, using full clip: {stderr.decode()[-200:]}")
        return input_path
    return output_path


async def _extract_clip_audio_segment(
    clip_audio_path: str,
    start_seconds: float,
    duration_seconds: float,
    output_path: str,
) -> bool:
    """Extract a segment from a clip's audio track. Returns True on success."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not clip_audio_path or not Path(clip_audio_path).exists():
        return False
    cmd = [
        ffmpeg,
        "-ss", str(start_seconds),
        "-t", str(duration_seconds),
        "-i", clip_audio_path,
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Clip audio extraction failed: {stderr.decode()[-200:]}")
        return False
    return True


async def _normalize_audio_to_aac(input_path: str, output_path: str) -> str:
    """Convert any audio file to AAC 44100Hz stereo for consistent concat."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return input_path
    cmd = [
        ffmpeg, "-i", input_path,
        "-c:a", "aac", "-ar", "44100", "-ac", "2", "-b:a", "192k",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Audio normalize failed for {input_path}: {stderr.decode()[-200:]}")
        return input_path
    return output_path


async def _concat_audio_segments(segment_paths: list[str], output_path: str) -> None:
    """Concatenate audio segments, normalizing all to AAC first."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    if len(segment_paths) == 1:
        shutil.copy2(segment_paths[0], output_path)
        return

    normalized = []
    out_dir = Path(output_path).parent
    for i, p in enumerate(segment_paths):
        norm_path = str(out_dir / f"norm_{i:02d}.aac")
        result = await _normalize_audio_to_aac(p, norm_path)
        normalized.append(result)
        dur = await _get_audio_duration(result)
        logger.info(f"  Audio piece [{i}]: {Path(p).name} -> {dur:.1f}s")

    concat_file = str(out_dir / "concat_mixed_audio.txt")
    with open(concat_file, "w") as f:
        for p in normalized:
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
    for p in normalized:
        Path(p).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Mixed audio concat failed: {stderr.decode()[-300:]}")


async def _apply_story_plan_durations(
    visual_assets: list,
    story_plan,
    audio_segment_paths: list[str],
) -> None:
    """Set visual asset durations from story_plan directives.

    clip_plays segments use clip_duration_seconds directly.
    narrate/narrate_over segments use the actual TTS file duration (or word-count estimate).
    """
    seg_by_seq = {seg.sequence_number: seg for seg in story_plan.segments}
    narration_idx = 0

    for asset in visual_assets:
        seg = seg_by_seq.get(asset.sequence_number)
        if not seg:
            logger.warning(f"  [{asset.sequence_number}] No matching segment in story_plan, keeping default")
            continue

        if seg.mode == "clip_plays":
            duration = seg.clip_duration_seconds or 6.0
            asset.duration_seconds = max(2.0, duration)
            logger.info(f"  [{asset.sequence_number}] clip_plays: {asset.duration_seconds:.1f}s")

        elif seg.mode in ("narrate", "narrate_over"):
            duration = 0.0
            if narration_idx < len(audio_segment_paths):
                seg_audio = audio_segment_paths[narration_idx]
                if Path(seg_audio).exists():
                    duration = await _get_audio_duration(seg_audio)
                narration_idx += 1

            if duration <= 0:
                words = len(seg.narration_text.split()) if seg.narration_text else 5
                duration = max(2.0, round(words / 2.5, 1))

            asset.duration_seconds = duration
            logger.info(f"  [{asset.sequence_number}] {seg.mode}: {asset.duration_seconds:.1f}s")


async def _build_mixed_audio(
    story_plan,
    audio_segment_paths: list[str],
    source_clips: list,
    output_dir: Path,
) -> str | None:
    """Build a mixed audio track: narration segments interleaved with clip audio.

    Returns path to the mixed audio file, or None if assembly fails.
    """
    narration_idx = 0
    audio_pieces = []
    fade_duration = 0.3

    for i, seg in enumerate(story_plan.segments):
        piece_path = str(output_dir / f"audio_piece_{i:02d}.aac")

        if seg.mode == "clip_plays":
            clip_idx = seg.source_clip_index or 0
            clip = source_clips[clip_idx] if clip_idx < len(source_clips) else None
            if not clip or not clip.audio_path:
                logger.warning(f"  Seg {i}: clip_plays but no audio_path for clip[{clip_idx}]")
                continue

            duration = seg.clip_duration_seconds or clip.duration_seconds or 8.0
            success = await _extract_clip_audio_segment(
                clip.audio_path,
                seg.clip_start_seconds,
                duration,
                piece_path,
            )
            if success:
                audio_pieces.append(piece_path)
                logger.info(f"  Seg {i}: clip_plays audio from clip[{clip_idx}] ({duration:.1f}s)")
            else:
                logger.warning(f"  Seg {i}: clip_plays audio extraction failed, segment will be silent")

        elif seg.mode in ("narrate", "narrate_over") and seg.narration_text:
            if narration_idx < len(audio_segment_paths):
                narration_file = audio_segment_paths[narration_idx]
                if Path(narration_file).exists():
                    audio_pieces.append(narration_file)
                    logger.info(f"  Seg {i}: narration[{narration_idx}] \"{seg.narration_text[:40]}...\"")
                narration_idx += 1

    if not audio_pieces:
        return None

    mixed_path = str(output_dir / "mixed_audio.aac")
    await _concat_audio_segments(audio_pieces, mixed_path)
    logger.info(f"Mixed audio assembled: {mixed_path} ({len(audio_pieces)} pieces)")
    return mixed_path


async def _concat_clips_with_audio(clip_paths: list[str], output_dir: Path, output_path: str) -> str:
    """Concatenate clips preserving any embedded audio (for clip_plays sync)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    concat_file = str(output_dir / "concat_list_av.txt")
    with open(concat_file, "w") as f:
        for p in clip_paths:
            f.write(f"file '{Path(p).resolve()}'\n")

    cmd = [
        ffmpeg, "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-ar", "44100", "-ac", "2",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    Path(concat_file).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"concat with audio failed: {stderr.decode()[-300:]}")

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    logger.info(f"Concatenated {len(clip_paths)} clips with audio: {size_mb:.1f}MB")
    return output_path


async def _overlay_narration(
    video_path: str,
    output_path: str,
    story_plan,
    visual_assets: list,
    audio_segment_paths: list[str],
    output_dir: Path,
) -> str:
    """Overlay narration segments on top of video at calculated timestamps.

    Clip audio plays naturally from the video. Narration is placed at exact
    timestamps based on cumulative visual segment durations, overriding
    clip audio when present.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    cumulative = 0.0
    narration_idx = 0
    placements = []

    for asset in visual_assets:
        seg_match = None
        for seg in story_plan.segments:
            if seg.sequence_number == asset.sequence_number:
                seg_match = seg
                break

        if seg_match and seg_match.mode in ("narrate", "narrate_over") and seg_match.narration_text:
            if narration_idx < len(audio_segment_paths):
                delay_ms = int(cumulative * 1000)
                placements.append((audio_segment_paths[narration_idx], delay_ms))
                logger.info(
                    f"  Narration [{narration_idx}] at {cumulative:.1f}s: "
                    f"\"{seg_match.narration_text[:40]}...\""
                )
                narration_idx += 1

        cumulative += asset.duration_seconds

    if not placements:
        shutil.copy2(video_path, output_path)
        return output_path

    inputs = ["-i", video_path]
    for path, _ in placements:
        inputs.extend(["-i", path])

    filter_parts = []
    for i, (_, delay_ms) in enumerate(placements):
        filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms},volume=1.5[n{i}]")

    clip_audio = "[0:a]volume=0.8[bg]"
    mix_inputs = "[bg]" + "".join(f"[n{i}]" for i in range(len(placements)))
    amix = f"{mix_inputs}amix=inputs={len(placements)+1}:duration=longest:normalize=0[aout]"

    filter_complex = ";".join([clip_audio] + filter_parts + [amix])

    cmd = [
        ffmpeg,
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"Narration overlay failed: {stderr.decode()[-300:]}")
        shutil.copy2(video_path, output_path)
        return output_path

    logger.info(f"Narration overlaid: {len(placements)} segments at calculated timestamps")
    return output_path


async def _concat_clips(clip_paths: list[str], audio_path: str, output_path: str) -> str:
    """Concatenate clips using ffmpeg concat demuxer + audio overlay, trimmed to audio length."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_duration = await _get_audio_duration(audio_path)

    concat_file = str(output_dir / "concat_list.txt")
    with open(concat_file, "w") as f:
        for p in clip_paths:
            abs_path = str(Path(p).resolve())
            f.write(f"file '{abs_path}'\n")

    concat_video = str(output_dir / "concat_only.mp4")
    cmd = [
        ffmpeg, "-f", "concat", "-safe", "0", "-i", concat_file,
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-an", "-y", concat_video,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"concat failed: {stderr.decode()[-300:]}")

    trim_args = []
    if audio_duration > 0:
        trim_args = ["-t", str(audio_duration + 0.5)]

    cmd2 = [
        ffmpeg, "-i", concat_video, "-i", audio_path,
        *trim_args,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-y", output_path,
    ]
    proc2 = await asyncio.create_subprocess_exec(
        *cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr2 = await proc2.communicate()
    if proc2.returncode != 0:
        raise RuntimeError(f"audio mux failed: {stderr2.decode()[-300:]}")

    Path(concat_file).unlink(missing_ok=True)
    Path(concat_video).unlink(missing_ok=True)

    size_mb = Path(output_path).stat().st_size / (1024 * 1024)
    logger.info(f"Assembled video: {output_path} ({size_mb:.1f}MB, {len(clip_paths)}, trimmed to {audio_duration:.1f}s)")
    return output_path


async def _verify_final_video(video_path: str) -> list[str]:
    """Verify the final video has correct audio, video, and reasonable duration."""
    issues = []
    ffprobe = shutil.which("ffprobe")
    if not ffprobe or not Path(video_path).exists():
        issues.append("Video file missing")
        return issues

    cmd = [
        ffprobe, "-v", "error", "-show_entries",
        "stream=codec_type,duration,codec_name",
        "-show_entries", "format=duration",
        "-of", "json", video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()

    import json
    try:
        info = json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        issues.append("Could not probe video file")
        return issues

    streams = info.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    if not has_video:
        issues.append("No video stream")
    if not has_audio:
        issues.append("No audio stream — voiceover is missing")

    fmt_duration = float(info.get("format", {}).get("duration", 0))
    if fmt_duration < 5:
        issues.append(f"Video too short: {fmt_duration:.1f}s")
    elif fmt_duration > 120:
        issues.append(f"Video too long: {fmt_duration:.1f}s")

    if has_audio:
        audio_stream = next(s for s in streams if s.get("codec_type") == "audio")
        audio_dur = float(audio_stream.get("duration", 0))
        if audio_dur < 5:
            issues.append(f"Audio too short: {audio_dur:.1f}s — voiceover likely missing")

    file_size = Path(video_path).stat().st_size
    if file_size < 100_000:
        issues.append(f"File suspiciously small: {file_size / 1024:.0f}KB")

    if not issues:
        logger.info(f"Video verified: {fmt_duration:.1f}s, {file_size / (1024*1024):.1f}MB, audio+video OK")

    return issues


async def video_assembly_node(state: ShortsPipelineState) -> dict:
    """Assemble the final short-form video."""
    logger.info("=== SHORTS: VIDEO ASSEMBLY ===")

    raw_assets = sorted(state.get("visual_assets", []), key=lambda a: a.sequence_number)
    audio_path = state.get("audio_path", "")
    audio_duration = state.get("audio_duration_seconds", 0.0)

    story_plan = state.get("story_plan")
    if story_plan:
        assets_by_seq = {}
        for asset in raw_assets:
            assets_by_seq.setdefault(asset.sequence_number, []).append(asset)

        visual_assets = []
        for seg in story_plan.segments:
            candidates = assets_by_seq.get(seg.sequence_number, [])
            best = None
            if seg.mode in ("clip_plays", "narrate_over"):
                for c in candidates:
                    if c.asset_type == "source_clip" and c.file_path:
                        best = c
                        break
            else:
                for c in candidates:
                    if c.asset_type in ("web_image", "stock_clip") and c.file_path:
                        best = c
                        break
            if not best:
                for c in candidates:
                    if c.file_path:
                        best = c
                        break
            if best:
                visual_assets.append(best)
            else:
                logger.warning(f"  [{seg.sequence_number}] No visual asset with file_path for {seg.mode}")
        logger.info(f"Rebuilt {len(visual_assets)} visual assets from story_plan (was {len(raw_assets)} raw)")
    else:
        seen_seq = {}
        for asset in raw_assets:
            seq = asset.sequence_number
            if seq not in seen_seq:
                seen_seq[seq] = asset
            elif asset.file_path and not seen_seq[seq].file_path:
                seen_seq[seq] = asset
        visual_assets = sorted(seen_seq.values(), key=lambda a: a.sequence_number)

    if not visual_assets:
        return {"errors": ["No visual assets for assembly"], "current_phase": "failed"}
    if not audio_path:
        return {"errors": ["No audio for assembly"], "current_phase": "failed"}

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"]
    output_dir.mkdir(parents=True, exist_ok=True)

    video_service = VideoAssemblyService(output_dir=str(output_dir))

    audio_segment_paths = state.get("audio_segment_paths", [])
    source_clips = state.get("source_clips", [])

    caption_segments = state.get("caption_segments") or []

    director_planned = state.get("director_planned", False)

    if director_planned:
        logger.info("Director-planned: using exact shot durations (skipping alignment)")
    elif story_plan:
        await _apply_story_plan_durations(visual_assets, story_plan, audio_segment_paths)
        logger.info(f"Using story_plan durations (skipping speech alignment)")
    else:
        if not caption_segments and audio_path:
            try:
                cs = get_caption_service()
                caption_segments = await cs.generate_word_timestamps(audio_path)
            except Exception as e:
                logger.warning(f"Pre-assembly caption gen failed: {e}")

        has_script_text = any(a.script_text for a in visual_assets if a.file_path)
        if caption_segments and has_script_text:
            _align_visuals_to_speech(visual_assets, caption_segments, audio_duration)
        elif caption_segments and not has_script_text:
            _distribute_by_word_count(visual_assets, caption_segments, audio_duration)
        else:
            stock_assets = [a for a in visual_assets if a.asset_type == "stock_clip" and a.file_path]
            image_assets = [a for a in visual_assets if a.asset_type in ("ai_image", "web_image") and a.file_path]
            stock_total = sum(a.duration_seconds for a in stock_assets)
            if audio_duration > 0 and image_assets:
                remaining_time = max(len(image_assets) * 2.0, audio_duration - stock_total)
                planned_total = sum(a.duration_seconds for a in image_assets) or 1.0
                scale = remaining_time / planned_total
                for asset in image_assets:
                    asset.duration_seconds = max(2.0, round(asset.duration_seconds * scale, 1))

    visual_assets = _split_long_segments(visual_assets)

    durations = [f"{a.duration_seconds:.1f}s" for a in visual_assets if a.file_path]
    logger.info(f"Duration budget: {audio_duration:.1f}s audio, segment durations: {durations}")

    content_mode = state.get("content_mode", "news_commentary")
    is_compilation = content_mode == "clip_compilation"
    compilation_items = state.get("compilation_items", [])
    seg_by_seq = {seg.sequence_number: seg for seg in story_plan.segments} if story_plan else {}

    clip_paths = []
    for asset in visual_assets:
        if not asset.file_path:
            logger.warning(f"[{asset.sequence_number}] Missing file, skipping")
            continue

        if asset.asset_type in ("stock_clip", "source_clip", "ai_video"):
            if is_compilation and asset.asset_type == "source_clip" and not story_plan:
                numbered_path = str(output_dir / f"numbered_{asset.sequence_number:02d}.mp4")
                item_idx = asset.sequence_number - 1
                label = ""
                if 0 <= item_idx < len(compilation_items):
                    label = f"#{asset.sequence_number}"
                await _add_number_overlay(
                    asset.file_path, numbered_path, label, asset.duration_seconds
                )
                clip_paths.append(numbered_path)
            elif story_plan and asset.asset_type == "source_clip":
                seg = seg_by_seq.get(asset.sequence_number)
                if seg and seg.clip_duration_seconds:
                    clip_audio = ""
                    clip_idx = seg.source_clip_index or 0
                    if clip_idx < len(source_clips) and source_clips[clip_idx].audio_path:
                        clip_audio = source_clips[clip_idx].audio_path
                    trimmed_path = str(output_dir / f"trimmed_{asset.sequence_number:02d}.mp4")
                    trimmed = await _trim_clip_segment(
                        asset.file_path, trimmed_path,
                        seg.clip_start_seconds, seg.clip_duration_seconds,
                        clip_audio_path=clip_audio,
                    )
                    clip_paths.append(trimmed)
                    has_audio_label = " (with audio)" if clip_audio else " (no audio)"
                    logger.info(
                        f"  [{asset.sequence_number}] Trimmed source clip: "
                        f"{seg.clip_start_seconds:.1f}s + {seg.clip_duration_seconds:.1f}s{has_audio_label}"
                    )
                else:
                    clip_paths.append(asset.file_path)
            else:
                clip_paths.append(asset.file_path)
        else:
            kb_path = str(output_dir / f"kb_{asset.sequence_number:02d}.mp4")
            await video_service.create_ken_burns_clip(
                image_path=asset.file_path,
                duration=asset.duration_seconds,
                output_path=kb_path,
                direction=asset.ken_burns_direction,
                width=1080,
                height=1920,
            )
            if story_plan:
                kb_with_audio = str(output_dir / f"kb_{asset.sequence_number:02d}_a.mp4")
                await _add_silent_audio(kb_path, kb_with_audio, asset.duration_seconds)
                clip_paths.append(kb_with_audio)
            else:
                clip_paths.append(kb_path)

    if not clip_paths:
        return {"errors": ["No clips produced for assembly"], "current_phase": "failed"}

    if story_plan and audio_segment_paths:
        mixed = await _build_mixed_audio(story_plan, audio_segment_paths, source_clips, output_dir)
        effective_audio = mixed if mixed else audio_path
        logger.info(f"Using mixed audio track (sequential narration + clip audio)")

        raw_video = str(output_dir / "raw_assembled.mp4")
        await _concat_clips(clip_paths, effective_audio, raw_video)
    else:
        effective_audio = audio_path
        raw_video = str(output_dir / "raw_assembled.mp4")
        await _concat_clips(clip_paths, effective_audio, raw_video)

    caption_audio = effective_audio
    if not effective_audio.endswith(".mp3"):
        mp3_path = str(output_dir / "caption_audio.mp3")
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg_bin, "-i", effective_audio, "-c:a", "libmp3lame", "-q:a", "2", "-y", mp3_path,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0 and Path(mp3_path).exists():
                caption_audio = mp3_path

    caption_service = get_caption_service()
    try:
        segments = caption_segments if caption_segments else await caption_service.generate_word_timestamps(caption_audio)

        subtitle_path = str(output_dir / "captions.ass")
        caption_service.generate_ass_subtitles(
            segments=segments,
            output_path=subtitle_path,
            video_width=1080,
            video_height=1920,
        )

        final_video = str(output_dir / "final_short.mp4")
        await caption_service.burn_captions(raw_video, subtitle_path, final_video)

        Path(raw_video).unlink(missing_ok=True)
        logger.info(f"Final video with captions: {final_video}")
        video_to_verify = final_video

    except Exception as e:
        logger.warning(f"Caption generation failed, using video without captions: {e}")
        final_video = str(output_dir / "final_short.mp4")
        Path(raw_video).rename(final_video)
        video_to_verify = final_video

    issues = await _verify_final_video(video_to_verify)
    if issues:
        logger.error(f"VERIFICATION FAILED: {issues}")
        return {
            "final_video_path": final_video,
            "current_phase": "failed",
            "errors": [f"Video verification failed: {'; '.join(issues)}"],
            "messages": [AIMessage(content=f"Video failed verification: {'; '.join(issues)}")],
        }

    return {
        "final_video_path": final_video,
        "current_phase": "metadata_generation",
        "messages": [AIMessage(content=f"Video assembled and verified: {final_video}")],
    }
