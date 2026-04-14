"""AI video sourcing node — generates video clips via Kling AI (FAL.ai).

Two-step process with scene chaining:
1. Generate scene images SEQUENTIALLY with Gemini — each scene receives the previous
   scene's image as context for visual continuity
2. Animate each scene image with Kling v3 image-to-video + Elements

Runs AFTER TTS so it knows exact audio durations per segment.
"""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)

SCENE_IMAGE_PROMPT_FIRST = (
    "This is my character reference image. The character is: {character_name}\n\n"
    "Generate a NEW image of this EXACT SAME character in this scene:\n\n"
    "{scene_description}\n\n"
    "CRITICAL: The character must look IDENTICAL to the reference image. "
    "Same face, same body, same texture, same outfit, same proportions. "
    "Do NOT change the character into something else. Do NOT make it a marble statue "
    "if the reference shows a worm, and vice versa. "
    "Vertical 9:16 portrait composition. Cinematic lighting. Photorealistic. "
    "Show the character MID-ACTION, not posing."
)

SCENE_IMAGE_PROMPT_CHAINED = (
    "I'm showing you TWO images. The character is: {character_name}\n\n"
    "1. FIRST IMAGE = CHARACTER REFERENCE — the character must ALWAYS look exactly like this.\n"
    "2. SECOND IMAGE = THE PREVIOUS SHOT — this is where the character was a moment ago.\n\n"
    "Generate the NEXT MOMENT in the character's journey. They are now:\n\n"
    "{scene_description}\n\n"
    "CRITICAL RULES:\n"
    "- Character MUST match image 1 (same face, body, outfit)\n"
    "- Do NOT turn the character into a marble statue or any other form — keep it as shown\n"
    "- This scene happens RIGHT AFTER image 2 — same location/era\n"
    "- The environment should look like the SAME PLACE as image 2\n"
    "- Character is MID-ACTION (walking, reaching, turning, reacting)\n"
    "- Vertical 9:16. Cinematic. Photorealistic."
)

CONTENT_POLICY_SOFTENER = (
    " NOTE: Depict the scene dramatically but tastefully. Show tension and atmosphere "
    "rather than explicit gore. Focus on expressions, shadows, and implied danger. PG-13."
)

CHARACTER_REF_PATHS = {
    "marble": lambda: settings.kling_marble_ref_urls,
    "worm": lambda: settings.kling_worm_ref_urls,
}


def _get_character_ref_path(character: str) -> str | None:
    """Get the first local reference image path for a character."""
    getter = CHARACTER_REF_PATHS.get(character)
    if not getter:
        return None
    urls = getter()
    if not urls:
        return None
    path = urls.split(",")[0].strip()
    return path if Path(path).exists() else None


def _compute_clip_durations(assets: list, total_audio_duration: float) -> list[int]:
    """Distribute audio duration across clips, returning per-clip durations (integers 3-15)."""
    n = len(assets)
    if n == 0:
        return []

    total_weight = sum(max(0.5, a.duration_seconds) for a in assets) or 1.0
    durations = []
    for a in assets:
        weight = max(0.5, a.duration_seconds)
        raw = (weight / total_weight) * total_audio_duration
        clamped = max(3, min(15, round(raw)))
        durations.append(clamped)

    current_total = sum(durations)
    target = round(total_audio_duration)
    diff = target - current_total
    while diff != 0:
        if diff > 0:
            idx = min(range(n), key=lambda i: durations[i])
            if durations[idx] < 15:
                durations[idx] += 1
                diff -= 1
            else:
                break
        else:
            idx = max(range(n), key=lambda i: durations[i])
            if durations[idx] > 3:
                durations[idx] -= 1
                diff += 1
            else:
                break

    return durations


async def _generate_scene_image_with_retry(
    image_gen, prompt: str, output_path: str, style_prefix: str,
    reference_image_paths: list[str] | None = None, max_retries: int = 3,
) -> str | None:
    """Generate a scene image with retry logic for transient errors (502, 503, etc.)."""
    for attempt in range(max_retries):
        try:
            return await image_gen.generate_image(
                prompt=prompt,
                output_path=output_path,
                style_prefix=style_prefix,
                reference_image_paths=reference_image_paths,
            )
        except Exception as e:
            err = str(e)
            if attempt < max_retries - 1 and ("502" in err or "503" in err or "timeout" in err.lower()):
                wait = (attempt + 1) * 5
                logger.warning(f"Scene image generation attempt {attempt+1} failed ({err[:80]}), retrying in {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise


async def _generate_scene_images_chained(
    pending: list, character: str, scene_img_dir: Path
) -> list[str | None]:
    """Generate scene images SEQUENTIALLY — each scene sees the previous scene for continuity."""
    from prolific.services.image_gen import get_image_gen_service
    image_gen = get_image_gen_service()

    char_ref_path = _get_character_ref_path(character)
    if not char_ref_path:
        logger.warning(f"No reference image found for character '{character}'")
        return [None] * len(pending)

    scene_images: list[str | None] = []
    prev_scene_path: str | None = None

    for i, asset in enumerate(pending):
        scene_desc = asset.video_prompt or asset.search_query or "standing in a neutral pose"
        output_path = str(scene_img_dir / f"scene_{asset.sequence_number:02d}.png")

        char_name = "Worm (cute cartoon worm with explorer hat)" if character == "worm" else "Marble Man (white marble statue figure)"

        if prev_scene_path and Path(prev_scene_path).exists():
            prompt = SCENE_IMAGE_PROMPT_CHAINED.format(character_name=char_name, scene_description=scene_desc)
            ref_paths = [char_ref_path, prev_scene_path]
        else:
            prompt = SCENE_IMAGE_PROMPT_FIRST.format(character_name=char_name, scene_description=scene_desc)
            ref_paths = [char_ref_path]

        try:
            result = await _generate_scene_image_with_retry(
                image_gen, prompt=prompt, output_path=output_path,
                style_prefix="", reference_image_paths=ref_paths,
            )
            if result:
                logger.info(f"[{asset.sequence_number}] Scene image: {output_path}")
                scene_images.append(result)
                prev_scene_path = result
            else:
                logger.warning(f"[{asset.sequence_number}] Scene image returned None")
                scene_images.append(None)
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Scene image failed after retries: {e}")
            scene_images.append(None)

    return scene_images


async def ai_video_sourcing_node(state: ShortsPipelineState) -> dict:
    """Generate AI video clips: chained Gemini scene images → Kling animation."""
    logger.info("=== SHORTS: AI VIDEO SOURCING (Gemini + Kling) ===")

    visual_assets = state.get("visual_assets", [])
    thread_id = state.get("thread_id", "unknown")
    selected_character = state.get("selected_character", "marble")
    audio_duration = state.get("audio_duration_seconds", 0.0)

    pending = [a for a in visual_assets if a.asset_type == "ai_video" and not a.file_path]
    if not pending:
        logger.info("No ai_video assets to generate")
        return {"visual_assets": visual_assets, "current_phase": "video_assembly"}

    director_planned = state.get("director_planned", False)

    if director_planned:
        clip_durations = [max(3, min(15, round(a.duration_seconds))) for a in pending]
        logger.info(
            f"Director-planned durations: {clip_durations} (sum={sum(clip_durations)}s)"
        )
    elif audio_duration > 0:
        clip_durations = _compute_clip_durations(pending, audio_duration)
        logger.info(
            f"Audio={audio_duration:.1f}s → {len(pending)} clips: "
            f"{clip_durations} (sum={sum(clip_durations)}s)"
        )
    else:
        clip_durations = [int(settings.kling_video_duration)] * len(pending)

    output_dir = Path(settings.shorts_output_dir) / thread_id
    scene_img_dir = output_dir / "scene_images"
    clip_dir = output_dir / "ai_clips"
    scene_img_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Generate scene images SEQUENTIALLY (chained for continuity)
    logger.info(f"Step 1: Generating {len(pending)} chained scene images with Gemini...")
    scene_images = await _generate_scene_images_chained(pending, selected_character, scene_img_dir)

    generated_images = sum(1 for s in scene_images if s)
    logger.info(f"Scene images: {generated_images}/{len(pending)} generated")

    # Step 2: Animate each scene image with Kling (parallel)
    logger.info(f"Step 2: Animating {len(pending)} clips with Kling...")
    from prolific.shorts.services.kling_video import get_kling_service
    kling = get_kling_service()

    vid_semaphore = asyncio.Semaphore(settings.kling_max_concurrent)
    generated = 0
    fallback_count = 0
    total_cost = 0.0

    async def _animate_one(asset, scene_image_path: str | None, clip_duration: int):
        nonlocal generated, fallback_count, total_cost
        async with vid_semaphore:
            prompt = asset.video_prompt or asset.search_query
            if not prompt:
                prompt = f"A scene related to: {asset.script_text[:100]}"

            prompt = f"{prompt}{CONTENT_POLICY_SOFTENER}"

            character = asset.character or selected_character
            output_path = str(clip_dir / f"ai_clip_{asset.sequence_number:02d}.mp4")

            if scene_image_path:
                import fal_client
                scene_url = await fal_client.upload_file_async(scene_image_path)

                try:
                    logger.info(
                        f"[{asset.sequence_number}] Kling v3 ({clip_duration}s): "
                        f"{prompt[:60]}..."
                    )
                    result = await asyncio.wait_for(
                        fal_client.run_async(
                            kling.image_to_video_endpoint,
                            arguments={
                                "prompt": prompt,
                                "start_image_url": scene_url,
                                "duration": str(clip_duration),
                                "aspect_ratio": "9:16",
                                "generate_audio": False,
                            },
                        ),
                        timeout=300,
                    )

                    video_url = result.get("video", {}).get("url")
                    if video_url:
                        raw_path = str(Path(output_path).with_suffix(".raw.mp4"))
                        import httpx
                        async with httpx.AsyncClient(timeout=120.0) as client:
                            resp = await client.get(video_url)
                            resp.raise_for_status()
                            Path(raw_path).write_bytes(resp.content)

                        await kling._normalize_video(raw_path, output_path)
                        Path(raw_path).unlink(missing_ok=True)

                        asset.file_path = output_path
                        asset.duration_seconds = float(clip_duration)
                        cost = clip_duration * settings.kling_cost_per_sec_usd
                        total_cost += cost
                        generated += 1
                        logger.info(f"[{asset.sequence_number}] Done: {output_path} (${cost:.2f})")
                        return

                except asyncio.TimeoutError:
                    logger.error(f"[{asset.sequence_number}] Kling timed out after 300s")
                except Exception as e:
                    logger.error(f"[{asset.sequence_number}] Kling failed: {e}")

            logger.warning(f"[{asset.sequence_number}] Falling back to Pexels")
            await _fallback_to_pexels(asset, thread_id)
            fallback_count += 1

    tasks = [
        _animate_one(a, si, d)
        for a, si, d in zip(pending, scene_images, clip_durations)
    ]
    await asyncio.gather(*tasks)

    logger.info(
        f"AI video complete: {generated}/{len(pending)} clips, "
        f"{fallback_count} fallbacks, ${total_cost:.2f}"
    )

    return {
        "visual_assets": visual_assets,
        "current_phase": "video_assembly",
        "messages": [AIMessage(
            content=f"AI video: {generated}/{len(pending)} clips "
                    f"(${total_cost:.2f}), {fallback_count} fallbacks"
        )],
    }


async def _fallback_to_pexels(asset, thread_id: str):
    """Fall back to Pexels stock clip when Kling generation fails."""
    try:
        from prolific.shorts.services.pexels import get_pexels_service
        pexels = get_pexels_service()

        output_path = str(
            Path(settings.shorts_output_dir) / thread_id / "clips"
            / f"fallback_{asset.sequence_number:02d}.mp4"
        )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        query = asset.search_query or asset.video_prompt or "nature scenery"
        result, _ = await pexels.fetch_clip(
            query=query,
            output_path=output_path,
            duration=asset.duration_seconds,
        )

        if result:
            asset.file_path = result
            asset.asset_type = "stock_clip"
            logger.info(f"Pexels fallback: {query[:40]}...")
        else:
            logger.warning(f"Pexels fallback also failed: {query[:40]}...")
    except Exception as e:
        logger.error(f"Pexels fallback error: {e}")
