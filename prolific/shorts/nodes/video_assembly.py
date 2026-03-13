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


async def _concat_clips(clip_paths: list[str], audio_path: str, output_path: str) -> str:
    """Concatenate clips using ffmpeg concat demuxer + audio overlay."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)

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

    cmd2 = [
        ffmpeg, "-i", concat_video, "-i", audio_path,
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-y", output_path,
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
    logger.info(f"Assembled video: {output_path} ({size_mb:.1f}MB, {len(clip_paths)} clips)")
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

    stock_assets = [a for a in visual_assets if a.asset_type == "stock_clip" and a.file_path]
    image_assets = [a for a in visual_assets if a.asset_type in ("ai_image", "web_image")]
    stock_total = sum(a.duration_seconds for a in stock_assets)

    if audio_duration > 0 and image_assets:
        remaining_time = audio_duration - stock_total
        per_image = max(2.0, remaining_time / len(image_assets))
        for asset in image_assets:
            asset.duration_seconds = round(per_image, 1)
        logger.info(
            f"Duration budget: {audio_duration:.1f}s audio, "
            f"{stock_total:.1f}s stock ({len(stock_assets)} clips), "
            f"{per_image:.1f}s per Ken Burns ({len(image_assets)} images)"
        )

    clip_paths = []
    for asset in visual_assets:
        if not asset.file_path:
            logger.warning(f"[{asset.sequence_number}] Missing file, skipping")
            continue

        if asset.asset_type == "stock_clip":
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
        segments = await caption_service.generate_word_timestamps(audio_path)

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
