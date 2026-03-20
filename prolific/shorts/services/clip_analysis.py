"""Clip content analysis - frame extraction, vision analysis, transcript fetching."""

import asyncio
import base64
import logging
import shutil
from pathlib import Path

from prolific.shorts.schemas import ClipContentUnderstanding, ClipVisualAnalysis

logger = logging.getLogger(__name__)

VISUAL_ANALYSIS_PROMPT = """Analyze these video frames from a clip. They are sequential frames from the same video.

Describe what you see:
1. people_visible: List every person you can identify by name (celebrities, athletes, politicians). If unknown, describe them ("man in suit", "woman with microphone").
2. actions_described: What is happening in each frame? What actions are being performed?
3. setting: Where does this take place? (studio, arena, outdoors, press conference, etc.)
4. on_screen_text: Any text, graphics, chyrons, or captions visible on screen.
5. emotional_tone: What is the emotional tone? (tense, celebratory, angry, casual, etc.)
6. visual_summary: A 2-3 sentence summary of what this clip shows.

Be specific and factual. Only name people you are confident you can identify."""

CONTENT_SUMMARY_PROMPT = """Based on this clip analysis, provide:
1. content_summary: A 2-3 sentence summary of what this clip is about
2. key_moments: List 3-5 specific moments or events that happen in the clip that a narrator could reference

TRANSCRIPT:
{transcript}

VISUAL ANALYSIS:
{visual_summary}

People visible: {people}
Actions: {actions}
Setting: {setting}

Be specific. Only include moments that are clearly supported by the transcript or visual evidence."""


async def extract_key_frames(clip_path: str, output_dir: str, num_frames: int = 6) -> list[str]:
    """Extract evenly-spaced key frames from a video clip."""
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return []

    duration = await _get_duration(clip_path)
    if duration <= 0:
        return []

    frames_dir = Path(output_dir) / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_paths = []
    for i in range(num_frames):
        timestamp = duration * (i + 1) / (num_frames + 1)
        output_path = str(frames_dir / f"frame_{i:02d}.jpg")

        cmd = [
            ffmpeg, "-ss", str(timestamp), "-i", clip_path,
            "-frames:v", "1", "-q:v", "2", "-y", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode == 0 and Path(output_path).exists():
            frame_paths.append(output_path)

    logger.info(f"Extracted {len(frame_paths)} frames from {clip_path}")
    return frame_paths


async def analyze_clip_visuals(
    frame_paths: list[str], context: str = ""
) -> ClipVisualAnalysis | None:
    """Analyze video frames with vision model to understand clip content."""
    if not frame_paths:
        return None

    try:
        from prolific.services.llm import get_llm_service
        llm_service = get_llm_service()

        pick = _pick_representative_frames(frame_paths, max_frames=4)

        content_blocks = [{"type": "text", "text": VISUAL_ANALYSIS_PROMPT}]
        for fp in pick:
            img_data = base64.b64encode(Path(fp).read_bytes()).decode()
            content_blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_data}"},
            })

        from langchain_core.messages import HumanMessage
        message = HumanMessage(content=content_blocks)

        llm = llm_service.get_llm("vision", temperature=0.3)
        from prolific.services.usage_tracker import LLMUsageCallbackHandler
        handler = LLMUsageCallbackHandler(model_name=llm_service.get_model_name("vision"))
        structured_llm = llm.with_structured_output(ClipVisualAnalysis)
        result = await structured_llm.ainvoke([message], config={"callbacks": [handler]})

        logger.info(f"Visual analysis: {result.visual_summary[:80]}...")
        return result

    except Exception as e:
        logger.warning(f"Visual analysis failed: {e}")
        return None


async def get_clip_transcript(url: str) -> str | None:
    """Get transcript from a YouTube video URL."""
    try:
        from prolific.services.web_fetch import WebFetchService
        service = WebFetchService()
        if not service._is_youtube_url(url):
            return None
        result = await service._fetch_youtube_transcript(url)
        if result and result.content:
            logger.info(f"Got transcript ({len(result.content)} chars) for {url}")
            return result.content
        return None
    except Exception as e:
        logger.warning(f"Transcript fetch failed for {url}: {e}")
        return None


async def build_content_understanding(
    clip_path: str,
    clip_url: str,
    output_dir: str,
    topic: str = "",
) -> ClipContentUnderstanding:
    """Full content analysis: transcript + visual analysis + summary."""
    transcript_task = get_clip_transcript(clip_url)
    frames_task = extract_key_frames(clip_path, output_dir)
    duration_task = _get_duration(clip_path)

    transcript, frame_paths, duration = await asyncio.gather(
        transcript_task, frames_task, duration_task
    )

    visual_analysis = await analyze_clip_visuals(frame_paths or [], context=topic)

    content_summary = ""
    key_moments = []
    if transcript or visual_analysis:
        content_summary, key_moments = await _generate_summary(
            transcript=transcript or "",
            visual_analysis=visual_analysis,
        )

    understanding = ClipContentUnderstanding(
        transcript=transcript or "",
        visual_analysis=visual_analysis,
        clip_duration_seconds=duration,
        content_summary=content_summary,
        key_moments=key_moments,
    )

    logger.info(
        f"Content understanding: {duration:.1f}s clip, "
        f"transcript={'yes' if transcript else 'no'}, "
        f"vision={'yes' if visual_analysis else 'no'}, "
        f"{len(key_moments)} key moments"
    )
    return understanding


async def _generate_summary(
    transcript: str,
    visual_analysis: ClipVisualAnalysis | None,
) -> tuple[str, list[str]]:
    """Use LLM to generate content summary and key moments."""
    try:
        from pydantic import BaseModel, Field
        from langchain_core.messages import HumanMessage, SystemMessage
        from prolific.services.llm import get_llm_service

        class SummaryOutput(BaseModel):
            content_summary: str = ""
            key_moments: list[str] = Field(default_factory=list)

        llm_service = get_llm_service()

        prompt = CONTENT_SUMMARY_PROMPT.format(
            transcript=transcript[:800] if transcript else "(no transcript available)",
            visual_summary=visual_analysis.visual_summary if visual_analysis else "(no visual analysis)",
            people=", ".join(visual_analysis.people_visible) if visual_analysis else "unknown",
            actions=", ".join(visual_analysis.actions_described) if visual_analysis else "unknown",
            setting=visual_analysis.setting if visual_analysis else "unknown",
        )

        result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=prompt),
                HumanMessage(content="Generate the summary and key moments."),
            ],
            output_schema=SummaryOutput,
            tier="research",
            temperature=0.3,
        )
        return result.content_summary, result.key_moments

    except Exception as e:
        logger.warning(f"Summary generation failed: {e}")
        return "", []


def _pick_representative_frames(frame_paths: list[str], max_frames: int = 4) -> list[str]:
    """Pick evenly-spaced representative frames."""
    if len(frame_paths) <= max_frames:
        return frame_paths
    step = len(frame_paths) / max_frames
    return [frame_paths[int(i * step)] for i in range(max_frames)]


async def _get_duration(path: str) -> float:
    """Get media duration in seconds via ffprobe."""
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
