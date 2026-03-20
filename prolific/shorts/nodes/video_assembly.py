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


MAX_IMAGE_DURATION = 7.0
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
        "-pix_fmt", "yuv420p", "-y", concat_video,
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


async def video_assembly_node(state: ShortsPipelineState) -> dict:
    """Assemble the final short-form video."""
    logger.info("=== SHORTS: VIDEO ASSEMBLY ===")

    visual_assets = sorted(state.get("visual_assets", []), key=lambda a: a.sequence_number)
    audio_path = state.get("audio_path", "")
    audio_duration = state.get("audio_duration_seconds", 0.0)

    if not visual_assets:
        return {"errors": ["No visual assets for assembly"], "current_phase": "failed"}
    if not audio_path:
        return {"errors": ["No audio for assembly"], "current_phase": "failed"}

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"]
    output_dir.mkdir(parents=True, exist_ok=True)

    video_service = VideoAssemblyService(output_dir=str(output_dir))

    caption_segments = state.get("caption_segments") or []
    if not caption_segments and audio_path:
        try:
            from prolific.shorts.services.caption import get_caption_service
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

    clip_paths = []
    for asset in visual_assets:
        if not asset.file_path:
            logger.warning(f"[{asset.sequence_number}] Missing file, skipping")
            continue

        if asset.asset_type in ("stock_clip", "source_clip"):
            if is_compilation and asset.asset_type == "source_clip":
                numbered_path = str(output_dir / f"numbered_{asset.sequence_number:02d}.mp4")
                item_idx = asset.sequence_number - 1
                label = ""
                if 0 <= item_idx < len(compilation_items):
                    label = f"#{asset.sequence_number}"
                await _add_number_overlay(
                    asset.file_path, numbered_path, label, asset.duration_seconds
                )
                clip_paths.append(numbered_path)
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
            clip_paths.append(kb_path)

    if not clip_paths:
        return {"errors": ["No clips produced for assembly"], "current_phase": "failed"}

    raw_video = str(output_dir / "raw_assembled.mp4")
    await _concat_clips(clip_paths, audio_path, raw_video)

    caption_service = get_caption_service()
    try:
        segments = caption_segments if caption_segments else await caption_service.generate_word_timestamps(audio_path)

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

        return {
            "caption_segments": segments,
            "subtitle_path": subtitle_path,
            "final_video_path": final_video,
            "current_phase": "metadata_generation",
            "messages": [AIMessage(content=f"Video assembled with captions: {final_video}")],
        }

    except Exception as e:
        logger.warning(f"Caption generation failed, using video without captions: {e}")
        final_video = str(output_dir / "final_short.mp4")
        Path(raw_video).rename(final_video)

        return {
            "final_video_path": final_video,
            "current_phase": "metadata_generation",
            "warnings": [f"Captions skipped: {e}"],
            "messages": [AIMessage(content=f"Video assembled (no captions): {final_video}")],
        }
