"""Clip Director — plans stock footage shots aligned to narration timing.

Runs AFTER TTS for news_commentary mode. Uses Whisper word-level timestamps
to plan what stock clips to show and when, ensuring:
1. Each clip matches what's being narrated at that moment
2. Clips flow visually from one to the next (no jarring cuts)
3. Precise timing aligned to the audio

This replaces the old visual_planning -> sourcing -> assembly-alignment flow
with a director-first approach borrowed from the AI video pipeline.
"""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.services.caption import get_caption_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class ClipShot(BaseModel):
    sequence_number: int
    start_time: float
    end_time: float
    narration_text: str = ""
    search_query: str = ""
    asset_type: str = "stock_clip"
    visual_description: str = ""
    ken_burns_direction: str = "zoom_in"


class ClipShotList(BaseModel):
    shots: list[ClipShot] = Field(default_factory=list)


CLIP_DIRECTOR_SYSTEM = """You are a visual director for a YouTube Short that uses REAL stock footage and photos.
You have EXACT word-level timing from the narration. Your job is to decide what to SHOW and WHEN,
so each clip matches the narration and flows smoothly into the next.

TOPIC: {topic}

FULL SCRIPT:
{script_text}

WORD-LEVEL TIMESTAMPS (every word with start/end time in seconds):
{timestamps}

YOUR TASK: Create a shot list where each shot:
1. Covers a COMPLETE sentence or thought — NEVER cut mid-sentence
2. Has start_time/end_time matching EXACTLY when those words are spoken
3. Has a search_query (4-6 words) that will find stock footage of EXACTLY what's being discussed
4. Flows visually from the previous shot (similar setting, related subject, smooth transition)

=== SEARCH QUERY RULES (MOST IMPORTANT) ===

The search_query is what we use to find stock footage. It MUST show what the narration is talking about.

If the narration says "ancient Romans used urine as mouthwash":
  GOOD: "ancient Roman clay amphora urine vessel"
  BAD: "person brushing teeth modern bathroom"

If the narration says "the ammonia in urine breaks down stains":
  GOOD: "chemical reaction laboratory close up"
  BAD: "ocean underwater generic blue"

If the narration says "this practice spread across the Roman Empire":
  GOOD: "ancient Roman Empire ruins columns"
  BAD: "world map generic"

EVERY search_query must:
- Include the SPECIFIC subject being discussed (species name, historical era, specific object)
- Match the EXACT moment in the narration, not the general topic
- Be concrete enough to return relevant footage (not abstract concepts)
- NEVER be a metaphor or analogy — always literal

=== VISUAL FLOW RULES ===

Shots must feel like a CONTINUOUS SEQUENCE, not a random slideshow.
Think of how a documentary editor would cut between shots.

GOOD flow (Roman teeth topic):
  Shot 1: Ancient Roman ruins establishing shot (wide)
  Shot 2: Roman amphora clay vessels close up (detail — SAME ERA)
  Shot 3: Roman marble bust face teeth (related subject — SAME ERA)
  Shot 4: Chemical laboratory beaker reaction (topic shift — science explanation)
  Shot 5: Modern dentist white teeth smile (present day comparison)

BAD flow (random, jarring):
  Shot 1: Drone shot of ocean
  Shot 2: Person brushing teeth
  Shot 3: Ancient ruins
  Shot 4: Random science lab
  Shot 5: Cat video

Adjacent shots should share at least ONE of: same era, same setting, same subject, same color palette.
When the narration shifts topic (e.g., from history to science), the visual can shift too — but do it
at a natural break, not randomly.

=== ASSET TYPE RULES ===

Choose asset_type per shot:
- "stock_clip" (PREFERRED, 70-80%): Moving video footage. Use for: environments, animals, people,
  machines, nature, anything with motion. Stock footage is more engaging than photos.
- "web_image": Still photos. Use ONLY for very specific things that won't have video: diagrams,
  historical paintings, microscope images, infographics, maps.

=== TIMING RULES ===

- Each shot's start_time = start of the first word spoken during this shot
- Each shot's end_time = end of the last word spoken during this shot
- MINIMUM 3.0 seconds per shot — if a sentence is under 3s, combine with adjacent
- MAXIMUM ~8.0 seconds per shot — split longer segments at natural pauses
- Aim for 5-7 shots for a 30-second short
- First shot should be the most visually striking (pattern interrupt)
- Vary ken_burns_direction across shots: zoom_in, zoom_out, pan_left, pan_right

=== FIRST 3 SECONDS ===

The first shot must STOP THE SCROLL. Pick the most visually arresting search query possible
for what's being said in the opening line. If the hook mentions something shocking or gross,
lean into it visually.

Return ONLY the shot list. Every shot must have all fields filled."""


def _format_timestamps(caption_segments: list) -> str:
    lines = []
    current_line = []

    for seg in caption_segments:
        word = seg.word.strip()
        if not word:
            continue
        current_line.append(f"{word}({seg.start_time:.2f}-{seg.end_time:.2f})")

        if word.endswith(('.', '?', '!', ',')):
            lines.append(" ".join(current_line))
            current_line = []

    if current_line:
        lines.append(" ".join(current_line))

    return "\n".join(lines)


async def clip_director_node(state: ShortsPipelineState) -> dict:
    """Plan stock footage shots aligned to narration timing."""
    logger.info("=== SHORTS: CLIP DIRECTOR ===")

    script = state.get("script")
    audio_path = state.get("audio_path", "")
    audio_duration = state.get("audio_duration_seconds", 0.0)
    topic = state.get("topic", "")

    if not script or not audio_path:
        return {"errors": ["Clip director needs script + audio"], "current_phase": "failed"}

    caption_service = get_caption_service()
    caption_segments = await caption_service.generate_word_timestamps(audio_path)
    logger.info(f"Got {len(caption_segments)} word timestamps ({audio_duration:.1f}s audio)")

    if not caption_segments:
        return {"errors": ["Whisper returned no timestamps"], "current_phase": "failed"}

    timestamps_str = _format_timestamps(caption_segments)

    llm_service = get_llm_service()
    prompt = CLIP_DIRECTOR_SYSTEM.format(
        topic=topic,
        script_text=script.full_text,
        timestamps=timestamps_str,
    )

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Create the shot list now. Align each shot to exact word timestamps."),
        ],
        output_schema=ClipShotList,
        tier="research",
        temperature=0.4,
    )

    shots = result.shots or []
    if not shots:
        return {"errors": ["Clip director produced no shots"], "current_phase": "failed"}

    for shot in shots:
        shot.start_time = max(0.0, shot.start_time)
        shot.end_time = min(audio_duration + 0.5, shot.end_time)
        if shot.end_time <= shot.start_time:
            shot.end_time = shot.start_time + 3.0

    if shots:
        for i in range(len(shots) - 1):
            next_start = shots[i + 1].start_time
            if next_start > shots[i].end_time:
                gap = next_start - shots[i].end_time
                shots[i].end_time = next_start
                if gap > 0.5:
                    logger.info(f"  Shot {shots[i].sequence_number}: extended {gap:.1f}s to fill gap")

        last = shots[-1]
        if last.end_time < audio_duration:
            last.end_time = audio_duration + 0.3
            logger.info(f"Extended last shot to {last.end_time:.1f}s")

    kb_directions = ["zoom_in", "zoom_out", "pan_left", "pan_right"]

    visual_assets = []
    for i, shot in enumerate(shots):
        duration = round(shot.end_time - shot.start_time, 1)
        duration = max(2.5, duration)

        if not shot.ken_burns_direction or shot.ken_burns_direction not in kb_directions:
            shot.ken_burns_direction = kb_directions[i % len(kb_directions)]

        asset = VisualAsset(
            sequence_number=shot.sequence_number,
            asset_type=shot.asset_type if shot.asset_type in ("stock_clip", "web_image") else "stock_clip",
            search_query=shot.search_query,
            narration_start=shot.start_time,
            narration_end=shot.end_time,
            duration_seconds=duration,
            script_text=shot.narration_text,
            ken_burns_direction=shot.ken_burns_direction,
        )
        visual_assets.append(asset)

    logger.info(f"Clip director planned {len(visual_assets)} shots:")
    for asset in visual_assets:
        logger.info(
            f"  [{asset.sequence_number}] {asset.narration_start:.1f}s-{asset.narration_end:.1f}s "
            f"({asset.duration_seconds:.1f}s) [{asset.asset_type}] q='{asset.search_query}'"
        )

    stock_count = sum(1 for a in visual_assets if a.asset_type == "stock_clip")
    web_count = sum(1 for a in visual_assets if a.asset_type == "web_image")

    return {
        "visual_assets": visual_assets,
        "caption_segments": caption_segments,
        "director_planned": True,
        "current_phase": "asset_generation",
        "messages": [AIMessage(
            content=f"Clip director: {len(shots)} shots ({stock_count} stock, {web_count} web)"
        )],
    }
