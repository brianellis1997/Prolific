"""One-off: regenerate thumbnails for specific long-form videos using the current
hook prompt, then upload via YouTube Data API thumbnails.set.

Usage:
  PYTHONPATH=. .venv/bin/python scripts/regen_thumbnails.py <video_id> [<video_id> ...]

For each video ID it fetches the title/topic from YouTube, brainstorms hooks
under the updated prompt (with prior video's chosen hook + the literal string
"WE CAN'T EXPLAIN THIS" as DO-NOT-REPEAT context), picks one, generates the
image via Gemini, and uploads the new thumbnail. Prints the chosen hook +
local artifact path for review.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.nodes.thumbnail_generation import _verify_thumbnail_text
from prolific.youtube.prompts import (
    THUMBNAIL_HOOK_EVAL_SYSTEM,
    THUMBNAIL_HOOK_SYSTEM,
    THUMBNAIL_PROMPT_TEMPLATE,
)
from prolific.youtube.services.image_gen import get_image_gen_service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

CREDS_PATH = "./youtube_credentials_slumber.json"


class HookEval(BaseModel):
    chosen_index: int = Field(description="0-based index of the best hook")
    rationale: str = Field(description="Why this hook wins")


def get_yt():
    import json
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with open(CREDS_PATH) as f:
        data = json.load(f)
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
    )
    return build("youtube", "v3", credentials=creds)


def fetch_video_meta(yt, video_id: str) -> dict:
    r = yt.videos().list(part="snippet", id=video_id).execute()
    if not r.get("items"):
        raise SystemExit(f"video not found: {video_id}")
    item = r["items"][0]
    title = item["snippet"]["title"]
    return {
        "id": video_id,
        "title": title,
        # The pipeline's "topic" is usually the pre-colon stem of the title.
        # For BIOGRAPHY this is the person ("Mansa Musa"); for others it's the headline.
        "topic": title.split("|")[0].strip(),
        "is_biography": any(
            tag in title.lower()
            for tag in (" life and ", " legacy", "story of", "the life of", "biography")
        ),
    }


async def pick_hook(topic: str, is_biography: bool, do_not_repeat: list[str]) -> str:
    llm = get_llm_service()

    sys_prompt = THUMBNAIL_HOOK_SYSTEM.format(topic=topic, is_biography=is_biography)
    if do_not_repeat:
        lines = [f'  - "{h}"' for h in do_not_repeat]
        sys_prompt += (
            "\n\n═══ RECENTLY-SHIPPED HOOKS — DO NOT REPEAT ═══\n"
            "Already used on this channel. Your output MUST be different:\n"
            + "\n".join(lines)
        )

    resp = await llm.invoke(
        messages=[
            SystemMessage(content=sys_prompt),
            HumanMessage(content="Generate 5 thumbnail hook options."),
        ],
        tier="research",
        temperature=0.9,
    )
    candidates = []
    for line in resp.content.strip().split("\n"):
        line = line.strip().lstrip("0123456789.)-: ")
        if line and len(line.split()) <= 6:
            candidates.append(line.strip('"').strip("'").upper())
    if not candidates:
        candidates = [resp.content.strip().split("\n")[0].strip().upper()]
    logger.info(f"  candidates: {candidates}")

    eval_user = f"Topic: {topic}\n\nHook candidates:\n" + "\n".join(
        f"[{i}] {c}" for i, c in enumerate(candidates)
    )
    if do_not_repeat:
        eval_user += (
            "\n\nRECENTLY-SHIPPED hooks (any candidate matching one of these verbatim, "
            "case-insensitive, must be REJECTED — pick another):\n"
            + "\n".join(f'  - "{h}"' for h in do_not_repeat)
        )
    eval_user += "\n\nPick the best one."

    res = await llm.invoke_with_structured_output(
        messages=[
            SystemMessage(content=THUMBNAIL_HOOK_EVAL_SYSTEM),
            HumanMessage(content=eval_user),
        ],
        output_schema=HookEval,
        tier="research",
        temperature=0.3,
    )
    chosen_idx = max(0, min(res.chosen_index, len(candidates) - 1))
    hook = candidates[chosen_idx]
    logger.info(f"  chosen: '{hook}' — {res.rationale}")
    return hook


async def regen_one(yt, video_id: str, do_not_repeat: list[str], dry_run: bool) -> str:
    meta = fetch_video_meta(yt, video_id)
    logger.info(f"\n▶ {video_id}  topic={meta['topic']!r}  is_biography={meta['is_biography']}")

    hook = await pick_hook(meta["topic"], meta["is_biography"], do_not_repeat)

    out_dir = Path("/tmp/regen_thumbs") / video_id
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = str(out_dir / "thumbnail_raw.png")
    final_path = str(out_dir / "thumbnail.jpg")

    img_svc = get_image_gen_service()
    base_prompt = THUMBNAIL_PROMPT_TEMPLATE.format(
        style=settings.youtube_image_style,
        topic=meta["topic"],
        hook_text=hook,
    )

    max_attempts = settings.youtube_thumbnail_max_verify_attempts
    prompt = base_prompt
    for attempt in range(1, max_attempts + 1):
        await img_svc.generate_image(prompt=prompt, output_path=raw_path)
        logger.info(f"  image generated (attempt {attempt}/{max_attempts}): {raw_path}")
        try:
            verification = await _verify_thumbnail_text(raw_path, hook)
        except Exception as exc:
            logger.warning(f"  vision check failed to run (non-fatal): {exc}")
            break
        if verification.text_intact:
            logger.info(
                f"  vision check PASSED: detected='{verification.detected_text}' — {verification.reason}"
            )
            break
        logger.warning(
            f"  vision check FAILED on attempt {attempt}: detected='{verification.detected_text}' — {verification.reason}"
        )
        if attempt < max_attempts:
            prompt = (
                base_prompt
                + "\n\nCRITICAL RETRY — PREVIOUS RENDER WAS REJECTED.\n"
                f"The previous image rendered the text as '{verification.detected_text}' "
                f"which failed verification: {verification.reason}. "
                f"Render the EXACT phrase '{hook}' with every word as one clean "
                f"unbroken unit. NO spaces inside words. NO line breaks inside words. "
                f"Spell every letter correctly. If you must wrap to multiple lines, "
                f"break ONLY at the spaces between words."
            )

    Image.open(raw_path).resize((1280, 720), Image.LANCZOS).save(
        final_path, "JPEG", quality=85, optimize=True
    )
    size_kb = Path(final_path).stat().st_size / 1024
    if size_kb > 2000:
        Image.open(raw_path).resize((1280, 720), Image.LANCZOS).save(
            final_path, "JPEG", quality=60, optimize=True
        )
    logger.info(f"  image saved: {final_path}")

    if dry_run:
        logger.info("  [DRY RUN] skipping upload")
        return hook

    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(final_path, mimetype="image/jpeg")
    yt.thumbnails().set(videoId=video_id, media_body=media).execute()
    logger.info(f"  ✓ uploaded thumbnail for {video_id}")
    return hook


async def main(video_ids: list[str], dry_run: bool):
    yt = get_yt()
    # Seed DO-NOT-REPEAT with the verbatim hook we know shipped twice this week.
    # The chosen hook from each video is fed into the next so the two regens diverge.
    do_not_repeat = ["WE CAN'T EXPLAIN THIS"]
    for vid in video_ids:
        chosen = await regen_one(yt, vid, do_not_repeat, dry_run)
        do_not_repeat.append(chosen)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ids", nargs="+", help="YouTube video IDs to regenerate")
    ap.add_argument("--dry-run", action="store_true", help="Generate locally, don't upload")
    args = ap.parse_args()
    asyncio.run(main(args.video_ids, args.dry_run))
