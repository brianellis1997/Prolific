"""AI video sourcing node — generates video clips via Kling AI (FAL.ai).

Two-step process:
1. Generate scene-specific starting images with Gemini (using character reference)
2. Animate each starting image with Kling v3 image-to-video + Elements

Runs AFTER TTS so it knows exact audio durations per segment.
"""

import asyncio
import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)

SCENE_IMAGE_PROMPT = (
    "This is my character reference. Generate a NEW image of this EXACT SAME character "
    "(same face, same marble texture, same toga, same hair) but in this scene:\n\n"
    "{scene_description}\n\n"
    "The character must look IDENTICAL to the reference — same marble skin, same curly hair, "
    "same toga draping. Place them in the described scene, already in the middle of the action. "
    "Vertical 9:16 portrait composition. Cinematic lighting. Photorealistic."
)

CONTENT_POLICY_SOFTENER = (
    "NOTE: Depict the scene in a dramatic but tasteful way. Show tension and atmosphere "
    "rather than explicit gore. Focus on expressions, shadows, and implied danger rather "
    "than graphic violence. Think PG-13 movie poster, not horror film."
)


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


async def _generate_scene_image(
    asset, character: str, output_dir: Path, semaphore: asyncio.Semaphore
) -> str | None:
    """Generate a scene-specific starting image using Gemini with character reference."""
    async with semaphore:
        from prolific.services.image_gen import get_image_gen_service
        image_gen = get_image_gen_service()

        ref_paths = settings.kling_marble_ref_urls if character == "marble" else settings.kling_worm_ref_urls
        ref_path = ref_paths.split(",")[0].strip() if ref_paths else None

        if not ref_path or not Path(ref_path).exists():
            logger.warning(f"No reference image for {character}")
            return None

        scene_desc = asset.video_prompt or asset.search_query or "standing in a neutral pose"
        prompt = SCENE_IMAGE_PROMPT.format(scene_description=scene_desc)

        output_path = str(output_dir / f"scene_{asset.sequence_number:02d}.png")

        try:
            result = await image_gen.generate_image(
                prompt=prompt,
                output_path=output_path,
                style_prefix="",
                reference_image_path=ref_path,
            )
            logger.info(f"[{asset.sequence_number}] Scene image generated: {output_path}")
            return result
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Scene image generation failed: {e}")
            return None


async def ai_video_sourcing_node(state: ShortsPipelineState) -> dict:
    """Generate AI video clips: Gemini scene images → Kling animation."""
    logger.info("=== SHORTS: AI VIDEO SOURCING (Gemini + Kling) ===")

    visual_assets = state.get("visual_assets", [])
    thread_id = state.get("thread_id", "unknown")
    selected_character = state.get("selected_character", "marble")
    audio_duration = state.get("audio_duration_seconds", 0.0)

    pending = [a for a in visual_assets if a.asset_type == "ai_video" and not a.file_path]
    if not pending:
        logger.info("No ai_video assets to generate")
        return {"visual_assets": visual_assets, "current_phase": "video_assembly"}

    if audio_duration > 0:
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

    # Step 1: Generate scene-specific starting images with Gemini
    logger.info(f"Step 1: Generating {len(pending)} scene images with Gemini...")
    img_semaphore = asyncio.Semaphore(3)
    scene_image_tasks = [
        _generate_scene_image(a, selected_character, scene_img_dir, img_semaphore)
        for a in pending
    ]
    scene_images = await asyncio.gather(*scene_image_tasks)

    generated_images = sum(1 for s in scene_images if s)
    logger.info(f"Scene images: {generated_images}/{len(pending)} generated")

    # Step 2: Animate each scene image with Kling
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

            prompt = f"{prompt} {CONTENT_POLICY_SOFTENER}"

            character = asset.character or selected_character
            output_path = str(clip_dir / f"ai_clip_{asset.sequence_number:02d}.mp4")

            if scene_image_path:
                import fal_client
                scene_url = await fal_client.upload_file_async(scene_image_path)

                refs = await kling._get_uploaded_refs(character)
                try:
                    logger.info(
                        f"[{asset.sequence_number}] Kling v3 ({clip_duration}s): "
                        f"{prompt[:60]}..."
                    )
                    elements = None
                    if refs:
                        elements = [{
                            "type": "image_set",
                            "frontal_image_url": refs["frontal_url"],
                            "reference_image_urls": refs.get("reference_urls") or [refs["frontal_url"]],
                        }]

                    result = await fal_client.run_async(
                        kling.image_to_video_endpoint,
                        arguments={
                            "prompt": f"@Element1 {prompt}" if elements else prompt,
                            "start_image_url": scene_url,
                            **({"elements": elements} if elements else {}),
                            "duration": str(clip_duration),
                            "aspect_ratio": "9:16",
                            "generate_audio": False,
                        },
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
        result = await pexels.fetch_clip(
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
