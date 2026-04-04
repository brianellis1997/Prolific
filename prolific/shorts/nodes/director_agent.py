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
3. Describes a vivid, specific scene the character is IN (mid-action, exploring, reacting)
4. Specifies a camera angle that's DIFFERENT from adjacent shots

CRITICAL — FIRST 3 SECONDS (PATTERN INTERRUPT):
The FIRST shot MUST be the most visually striking, dramatic, and attention-grabbing shot.
This is where 90% of viewers decide to keep watching or scroll away.
- Use a DYNAMIC camera angle (low angle, dutch angle, or extreme close-up)
- Show the character in the MOST visually interesting moment of the whole video
- It should make viewers think "what the hell is going on?" and NEED to keep watching
- Do NOT start with a slow wide establishing shot — that's boring. Start IN THE ACTION.

TIMING RULES:
- Each shot's start_time = the start of the first word in that shot
- Each shot's end_time = the end of the last word in that shot (+ up to 0.3s buffer)
- HARD MINIMUM: 3.0 seconds per shot (the AI video generator CANNOT make clips shorter)
- HARD MAXIMUM: 5.0 seconds per shot
- If a narration segment is under 3 seconds, you MUST combine it with the adjacent segment
  to create a longer shot. NEVER plan a shot under 3.0 seconds.
- If a narration segment is over 5 seconds, split it at a natural pause
- Let the NARRATION TIMING decide how many shots you need — do NOT target a specific count
- EVERY shot must be between 3.0 and 5.0 seconds. NO EXCEPTIONS.

DYNAMIC SHOT LENGTH — vary based on the narrative moment:
- Quick action cuts: 3.0 seconds
- Movement/exploration: 3.5-4.0 seconds
- Emotional beats, reveals, or key moments: 4.0-5.0 seconds (let them breathe)
- The FINAL shot: 4.0-5.0 seconds (give the closer weight)

IMPORTANT: Use the character name from the CHARACTER section above in your scene descriptions.
If the character is "Worm", write "Worm does X." If it's "Marble Man", write "Marble Man does X."
NEVER write the wrong character name — check the CHARACTER section.

CONTINUOUS JOURNEY RULES (THIS IS THE MOST IMPORTANT SECTION):
The video must feel like ONE CONTINUOUS JOURNEY, not a slideshow of random scenes.
Think of it as a camera following the character through a location in real-time.

- Shot 1: character ARRIVES (walks in, appears, portal opens — whatever fits)
- Shot 2-8: character MOVES THROUGH the environment, discovering things along the way
- Each shot picks up roughly where the last one left off SPATIALLY
- The character should be in a SIMILAR environment across consecutive shots
  (don't jump from a market to a throne room to a field — that's a slideshow)
- If the topic covers multiple eras, spend 3-4 shots PER ERA before transitioning
- Transitions between eras should be DELIBERATE (character walks through a door,
  a flash of light, a time warp effect)
- Final shot: character REACTS to everything they've seen (amazement, exhaustion, laughter)

THINK OF IT LIKE A MOVIE SCENE, NOT A POWERPOINT:
BAD (slideshow): Market shot → Kitchen shot → Castle shot → Farm shot
GOOD (journey): Character walks INTO market → looks at merchant stalls → picks up
  exotic spice → gets bumped by a passing cart → watches a performer → exits through
  the gate

The character should be MOVING through scenes (walking, turning, reaching, reacting).
OTHER PEOPLE should be present — crowds, merchants, workers, nobles.
Include era-appropriate props, architecture, clothing, food, tools.
Keep descriptions PG-13 — focus on wonder and discovery.

CAMERA ANGLE OPTIONS (NEVER use the same angle twice in a row):
- "wide establishing shot" — full scene, character small in environment
- "medium shot" — waist up, actions and expressions
- "close-up" — face or hands, emotional beat
- "extreme close-up" — ONE specific detail (a tool, an eye, a wound)
- "bird's eye view" — straight down, reveals scale
- "low angle" — looking UP at character, imposing/powerful
- "over-the-shoulder" — behind character, their POV
- "dutch angle" — tilted, creates tension/unease
- "tracking shot" — camera follows character movement
- "push-in" — slow zoom toward subject, builds intensity

PACING PATTERN: alternate between wide and tight shots. Never do two wide
shots in a row or two close-ups in a row. The rhythm should be:
wide → close → medium → extreme close → wide → etc.

EXAMPLE (for a 15-second narration about a medieval market — notice the CONTINUOUS JOURNEY):

Shot 1: start=0.0, end=3.0, narration="You would NOT survive a day in a medieval market."
  scene: "Low angle. Character steps through a massive stone archway into a chaotic, colorful marketplace. Crowds swarm around them. Morning light floods in."
  camera: "low angle"

Shot 2: start=3.1, end=5.8, narration="The smell hits you before you even see it."
  scene: "Close-up. Character's face reacts — nose wrinkles, eyes widen — as they look at a merchant's stall piled with raw fish and hanging meats. Flies buzz around."
  camera: "close-up"

Shot 3: start=5.9, end=8.5, narration="Merchants scream prices in three different languages."
  scene: "Medium shot. Character turns their head left and right as two bearded merchants on either side wave fabrics and spices, shouting at them. Bustling crowd behind."
  camera: "medium shot"

Shot 4: start=8.6, end=11.5, narration="A cart nearly runs you over."
  scene: "Tracking shot. Character jumps sideways as a wooden cart pulled by a donkey barrels through the narrow market lane. Mud splashes. People scatter."
  camera: "tracking shot"

Shot 5: start=11.6, end=15.0, narration="And that's just the first five minutes."
  scene: "Bird's eye view. Camera pulls up to reveal the ENTIRE sprawling market — thousands of people, hundreds of stalls, extending to the city walls. Character is a tiny figure in the middle."
  camera: "bird's eye view"

Notice: 5 shots, CONTINUOUS JOURNEY. Character walks in → smells food → hears merchants → dodges cart → camera reveals scale. Each shot follows from the last.

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
        if raw_duration < 2.5:
            logger.warning(
                f"Shot {shot.sequence_number} is only {raw_duration:.1f}s — "
                f"Director should have combined this with an adjacent shot"
            )
        kling_duration = max(3.0, min(5.0, round(raw_duration)))

        asset = VisualAsset(
            sequence_number=shot.sequence_number,
            asset_type="ai_video",
            video_prompt=shot.scene_description,
            search_query=shot.scene_description[:80],
            character=character,
            narration_start=shot.start_time,
            narration_end=shot.end_time,
            duration_seconds=float(kling_duration),
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

    # Fix gaps between shots: each clip should run from its start to the NEXT shot's start.
    # This fills the entire audio duration with video (no silent gaps that cause drift).
    if shots:
        for i in range(len(shots) - 1):
            next_start = shots[i + 1].start_time
            if next_start > shots[i].end_time:
                gap = next_start - shots[i].end_time
                shots[i].end_time = next_start
                if gap > 0.5:
                    logger.info(f"  Shot {shots[i].sequence_number}: extended by {gap:.1f}s to fill gap before next shot")

        # Last shot extends to cover full audio
        last = shots[-1]
        if last.end_time < audio_duration:
            last.end_time = audio_duration + 0.3
            logger.info(f"Extended last shot to {last.end_time:.1f}s to cover full audio")

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
