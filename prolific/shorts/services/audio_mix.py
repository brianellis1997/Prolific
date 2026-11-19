import asyncio
import hashlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"
MUSIC_TRACKS = [
    "Twinkle.mp3", "On_The_Flip.mp3", "Misdirection.mp3",
    "Down_The_Rabbit_Hole.mp3", "High_Noon.mp3", "A_Stroll.mp3",
]
MUSIC_GAIN = 0.16
WHOOSH_GAIN = 0.30
RISER_GAIN = 0.28
IMPACT_GAIN = 0.45


def pick_music(seed: str) -> Path | None:
    tracks = [MEDIA_DIR / "music" / t for t in MUSIC_TRACKS if (MEDIA_DIR / "music" / t).exists()]
    if not tracks:
        return None
    return tracks[int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(tracks)]


def plan_sfx(
    cut_times: list[float],
    payoff_time: float | None,
    duration: float,
    riser_seconds: float = 1.6,
) -> list[tuple[str, float, float]]:
    events: list[tuple[str, float, float]] = []
    has_payoff = payoff_time is not None and 2.0 < payoff_time < duration - 1.0
    for i, t in enumerate(cut_times):
        if i % 2 == 0 or not (0.8 < t < duration - 0.8):
            continue
        if has_payoff and payoff_time - riser_seconds - 0.4 <= t <= payoff_time + 0.6:
            continue
        events.append(("whoosh", max(0.0, t - 0.12), WHOOSH_GAIN))
    if has_payoff:
        events.append(("riser", max(0.0, payoff_time - riser_seconds), RISER_GAIN))
        events.append(("impact", payoff_time, IMPACT_GAIN))
    return sorted(events, key=lambda e: e[1])


def payoff_time_from_script(script, segments) -> float | None:
    if not script or not segments:
        return None
    lead_words = len(f"{getattr(script, 'hook', '')} {getattr(script, 'setup', '')}".split())
    if lead_words <= 0 or lead_words >= len(segments):
        return None
    return float(segments[lead_words].start_time)


async def _probe_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    proc = await asyncio.create_subprocess_exec(
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        return 0.0


async def mix_short_audio(
    narration_path: str,
    output_path: str,
    seed: str,
    cut_times: list[float],
    payoff_time: float | None,
    tail_seconds: float = 0.6,
) -> str | None:
    ffmpeg = shutil.which("ffmpeg")
    music = pick_music(seed)
    if not ffmpeg or not music:
        return None
    voice_seconds = await _probe_seconds(Path(narration_path))
    if voice_seconds <= 0:
        return None
    total = voice_seconds + tail_seconds
    riser = MEDIA_DIR / "sfx" / "riser.mp3"
    riser_seconds = await _probe_seconds(riser) if riser.exists() else 1.6
    events = [
        e for e in plan_sfx(cut_times, payoff_time, voice_seconds, riser_seconds or 1.6)
        if (MEDIA_DIR / "sfx" / f"{e[0]}.mp3").exists()
    ]

    inputs = ["-i", narration_path, "-stream_loop", "-1", "-i", str(music)]
    for name, _, _ in events:
        inputs += ["-i", str(MEDIA_DIR / "sfx" / f"{name}.mp3")]
    parts = [
        f"[1:a]atrim=0:{total:.3f},asetpts=N/SR/TB,volume={MUSIC_GAIN}[mus]",
        "[0:a]asplit=2[voice][key]",
        "[mus][key]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[bed]",
    ]
    labels = ["[voice]", "[bed]"]
    for i, (_, start, gain) in enumerate(events):
        ms = int(start * 1000)
        parts.append(f"[{i + 2}:a]adelay={ms}|{ms},volume={gain}[s{i}]")
        labels.append(f"[s{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[mix]")
    parts.append(f"[mix]atrim=0:{total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[out]")

    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(parts), "-map", "[out]",
        "-ar", "48000", "-c:a", "aac", "-b:a", "192k", "-y", output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not Path(output_path).exists():
        logger.warning(f"Sound design mix failed, using plain narration: {stderr.decode()[-300:]}")
        return None
    logger.info(
        f"Sound design: music {music.name}, {len(events)} sfx "
        f"({', '.join(f'{n}@{s:.1f}s' for n, s, _ in events)}), payoff {payoff_time if payoff_time is None else round(payoff_time, 1)}s"
    )
    return output_path
