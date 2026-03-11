"""Video assembly node - creates final video from images + audio."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.youtube.services.video import get_video_assembly_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def video_assembly_node(state: YouTubePipelineState) -> dict:
    """Assemble the final video with Ken Burns effects and narration audio."""
    logger.info("=== VIDEO ASSEMBLY ===")

    image_assets = state["image_assets"]
    audio_chunks = state["audio_chunks"]
    final_audio_path = state["final_audio_path"]
    thread_id = state["thread_id"]

    video_service = get_video_assembly_service()
    output_dir = Path(settings.youtube_output_dir) / thread_id / "video"
    output_dir.mkdir(parents=True, exist_ok=True)

    usable_images = sorted(
        [a for a in image_assets if a.file_path],
        key=lambda a: a.section_number,
    )

    if not usable_images:
        return {
            "errors": ["No images available for video assembly"],
            "current_phase": "failed",
        }

    audio_by_section = {c.section_number: c for c in audio_chunks}

    clip_paths = []
    for idx, asset in enumerate(usable_images):
        chunk = audio_by_section.get(asset.section_number)
        duration = chunk.duration_seconds if chunk else asset.duration_seconds

        clip_path = str(output_dir / f"clip_{asset.section_number:02d}.mp4")
        await video_service.create_ken_burns_clip(
            image_path=asset.file_path,
            duration=duration,
            output_path=clip_path,
            direction=asset.ken_burns_direction,
            fade_in=3.0 if idx == 0 else 0.0,
        )
        clip_paths.append(clip_path)

    final_video_path = str(
        Path(settings.youtube_output_dir) / thread_id / "final_video.mp4"
    )

    await video_service.assemble_video(
        clip_paths=clip_paths,
        audio_path=final_audio_path,
        output_path=final_video_path,
    )

    logger.info(f"Video assembled: {final_video_path}")

    return {
        "final_video_path": final_video_path,
        "current_phase": "metadata_generation",
        "messages": [AIMessage(content=f"Video assembled: {final_video_path}")],
    }
