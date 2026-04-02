"""Director Agent — analyzes narration timing and creates a precise shot list.

Runs AFTER TTS generation. Uses Whisper word-level timestamps to understand
exactly when each word is spoken, then plans visual shots that align perfectly
with the narration. Each shot covers a complete thought/sentence and has an
exact duration matching the audio timing.

This replaces visual_planning for AI video mode.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.services.caption import get_caption_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class Shot(BaseModel):
    sequence_number: int
    start_time: float
    end_time: float
    narration_text: str = ""
    scene_description: str = ""
    camera_angle: str = ""


class ShotList(BaseModel):
    shots: list[Shot] = Field(default_factory=list)
    character: str = "marble"


MARBLE_DESC = (
    "Marble Man — A photorealistic male figure made of white marble stone, "
    "like a Greek sculpture come to life. Curly marble hair, toga, white marble eyes."
)
WORM_DESC = (
    "Worm — A cute 2-foot-tall cartoon worm with big brown eyes, pink-brown "
    "segmented body, explorer hat, and small boots."
)


DIRECTOR_SYSTEM = """You are a film director creating a shot list for a 30-second YouTube Short.
You have EXACT word-level timing from the narration audio. Your job is to decide where each
visual shot starts and ends, what it shows, and how the camera frames it.

TOPIC: {topic}
CHARACTER: {character_description}

FULL SCRIPT:
{script_text}

WORD-LEVEL TIMESTAMPS (every word with exact start/end time in seconds):
{timestamps}

SCENE IDEAS (from topic research — use as inspiration, not requirements):
{scene_ideas}

YOUR TASK: Create a shot list where each shot:
1. Covers a COMPLETE sentence or thought — NEVER cut mid-sentence
2. Has a start_time and end_time that match EXACTLY where those words are spoken
3. Describes a vivid, specific scene the character is IN (mid-action, not static)
4. Specifies a camera angle that's DIFFERENT from adjacent shots

TIMING RULES:
- Each shot's start_time = the start of the first word in that shot
- Each shot's end_time = the end of the last word in that shot (+ up to 0.5s buffer)
- Minimum shot duration: 3 seconds (Kling AI constraint)
- Maximum shot duration: 10 seconds (longer clips have lower quality)
- If a sentence is under 3 seconds, COMBINE it with the adjacent sentence
- If a sentence is over 10 seconds, SPLIT it at a natural pause point
- Aim for 4-7 shots total

SCENE DESCRIPTION RULES:
- The character is the MAIN SUBJECT but can interact with OTHER FIGURES
- For vs/comparison topics: show BOTH sides (e.g., character as a modern athlete in one shot,
  then as an ancient warrior in the next, or facing off against a contrasting figure)
- Describe what the character is DOING (mid-action, not beginning an action)
- OTHER PEOPLE can appear in scenes (opponents, crowds, helpers, enemies)
- Include specific era-appropriate props, setting details, lighting
- Each scene should feel like the NEXT MOMENT in a continuous story
- Vary settings but maintain narrative flow
- Keep descriptions PG-13 — dramatic atmosphere, NOT explicit violence/gore

CAMERA ANGLE OPTIONS (use variety):
- "wide establishing shot" — shows full scene, character in environment
- "medium shot" — waist up, good for actions and expressions
- "close-up" — face/hands, emotional moments
- "extreme close-up" — specific detail (a tool, an object, eyes)
- "bird's eye view" — looking straight down
- "low angle" — looking up at character, makes them imposing
- "over-the-shoulder" — from behind character, looking at what they see
- "dutch angle" — tilted frame, creates unease

EXAMPLE (for a 12-second narration about gladiators):
Word timestamps: "Imagine(0.0-0.4) being(0.4-0.6) thrown(0.6-0.9) into(0.9-1.1) the(1.1-1.2) Colosseum(1.2-1.8) ...(pause)... Gladiators(3.5-4.0) trained(4.0-4.3) for(4.3-4.5) years(4.5-4.8)..."

Shot 1: start=0.0, end=3.3, narration="Imagine being thrown into the Colosseum with nothing but a wooden sword."
  scene: "Wide establishing shot. Character grips a crude wooden sword in a dark stone tunnel, torchlight flickering on wet walls. The bright arena archway looms ahead. Dust motes in the light."
  camera: "wide establishing shot"

Shot 2: start=3.5, end=7.2, narration="Gladiators trained for years just to survive a single fight."
  scene: "Medium shot. Character swings a heavy practice sword at a wooden post in a sandy training yard. Other fighters spar in the background. Harsh midday sun, sweat on marble skin."
  camera: "medium shot"

Return ONLY the shot list. Every shot must have all fields filled."""


def _select_character(topic: str) -> str:
    """Pick character based on config and topic."""
    mode = settings.kling_character_mode
    if mode in ("marble", "worm"):
        return mode
    if mode == "alternate":
        hour = datetime.now(ZoneInfo("America/New_York")).hour
        return "marble" if hour in (9, 16) else "worm"
    light_keywords = ["cute", "funny", "food", "sleep", "brush", "wash", "pet"]
    return "worm" if any(kw in topic.lower() for kw in light_keywords) else "marble"


def _format_timestamps(caption_segments: list) -> str:
    """Format word timestamps for the LLM prompt."""
    lines = []
    current_line = []
    current_end = 0.0

    for seg in caption_segments:
        word = seg.word.strip()
        if not word:
            continue
        current_line.append(f"{word}({seg.start_time:.2f}-{seg.end_time:.2f})")
        current_end = seg.end_time

        if word.endswith(('.', '?', '!', ',')):
            lines.append(" ".join(current_line))
            current_line = []

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


def _shots_to_visual_assets(shots: list[Shot], character: str) -> list[VisualAsset]:
    """Convert Director shots to VisualAssets with exact durations."""
    assets = []
    for shot in shots:
        raw_duration = shot.end_time - shot.start_time
        duration = max(3.0, min(15.0, round(raw_duration)))

        asset = VisualAsset(
            sequence_number=shot.sequence_number,
            asset_type="ai_video",
            video_prompt=shot.scene_description,
            search_query=shot.scene_description[:80],
            character=character,
            duration_seconds=float(duration),
            script_text=shot.narration_text,
            ken_burns_direction="zoom_in",
        )
        assets.append(asset)
    return assets


async def director_agent_node(state: ShortsPipelineState) -> dict:
    """Analyze narration timing and create a precise shot list for AI video generation."""
    logger.info("=== SHORTS: DIRECTOR AGENT ===")

    script = state.get("script")
    audio_path = state.get("audio_path", "")
    audio_duration = state.get("audio_duration_seconds", 0.0)
    topic = state.get("topic", "")
    scene_ideas = state.get("scene_ideas", [])

    if not script or not audio_path:
        return {"errors": ["Director needs script + audio"], "current_phase": "failed"}

    character = _select_character(topic)
    character_description = MARBLE_DESC if character == "marble" else WORM_DESC
    logger.info(f"Character: {character}")

    # Step 1: Get word-level timestamps from Whisper
    logger.info("Step 1: Analyzing narration timing with Whisper...")
    caption_service = get_caption_service()
    caption_segments = await caption_service.generate_word_timestamps(audio_path)
    logger.info(f"Got {len(caption_segments)} word timestamps ({audio_duration:.1f}s audio)")

    if not caption_segments:
        return {"errors": ["Whisper returned no timestamps"], "current_phase": "failed"}

    timestamps_str = _format_timestamps(caption_segments)
    scene_ideas_str = "\n".join(f"- {s}" for s in scene_ideas) if scene_ideas else "(none)"

    # Step 2: Director LLM creates shot list
    logger.info("Step 2: Director planning shot list...")
    llm_service = get_llm_service()

    prompt = DIRECTOR_SYSTEM.format(
        topic=topic,
        character_description=character_description,
        script_text=script.full_text,
        timestamps=timestamps_str,
        scene_ideas=scene_ideas_str,
    )

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Create the shot list now. Align each shot to exact word timestamps."),
        ],
        output_schema=ShotList,
        tier="research",
        temperature=0.4,
    )

    shots = result.shots or []
    if not shots:
        return {"errors": ["Director produced no shots"], "current_phase": "failed"}

    # Validate and fix shot timing
    for shot in shots:
        shot.start_time = max(0.0, shot.start_time)
        shot.end_time = min(audio_duration + 0.5, shot.end_time)
        if shot.end_time <= shot.start_time:
            shot.end_time = shot.start_time + 3.0

    # Log the shot list
    logger.info(f"Director planned {len(shots)} shots:")
    for shot in shots:
        dur = shot.end_time - shot.start_time
        logger.info(
            f"  Shot {shot.sequence_number}: {shot.start_time:.1f}s-{shot.end_time:.1f}s "
            f"({dur:.1f}s) [{shot.camera_angle}]"
        )
        logger.info(f"    Narration: {shot.narration_text[:60]}...")
        logger.info(f"    Scene: {shot.scene_description[:60]}...")

    # Convert to VisualAssets
    visual_assets = _shots_to_visual_assets(shots, character)

    total_planned = sum(a.duration_seconds for a in visual_assets)
    logger.info(
        f"Shot list: {len(visual_assets)} shots, "
        f"total {total_planned:.0f}s planned vs {audio_duration:.1f}s audio"
    )

    return {
        "visual_assets": visual_assets,
        "selected_character": character,
        "caption_segments": caption_segments,
        "director_planned": True,
        "current_phase": "ai_video_sourcing",
        "messages": [AIMessage(
            content=f"Director: {len(shots)} shots planned, character={character}"
        )],
    }
