"""Stock clip sourcing node - searches, evaluates, and downloads the best clips."""

import logging
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.services.clip_selector import ClipCandidate, select_best_clip
from prolific.shorts.services.pexels import get_pexels_service
from prolific.shorts.services.pixabay import get_pixabay_service
from prolific.shorts.services.shorts_history import get_shorts_history_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def _download_thumbnail_bytes(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None


async def _search_and_select(
    pexels,
    query: str,
    used_video_ids: set,
    scene_description: str,
    narration_text: str,
    previous_thumbnail: bytes | None,
) -> tuple[list[dict], int]:
    """Search Pexels, get candidates, use vision to pick the best one.

    Returns (candidates, best_index) where candidates are dicts with video info.
    """
    queries_to_try = [query]
    words = query.split()
    if len(words) > 3:
        queries_to_try.append(" ".join(words[:3]))
    if len(words) > 2:
        queries_to_try.append(" ".join(words[:2]))

    for q in queries_to_try:
        for page in range(1, 3):
            videos = await pexels.search_videos(q, page=page, per_page=8)
            if not videos:
                if page == 1:
                    logger.info(f"No Pexels results for '{q}', trying broader query")
                break

            candidates = pexels.get_candidates(videos, used_video_ids)
            if not candidates:
                logger.info(f"All Pexels page {page} results for '{q}' already used")
                continue

            if len(candidates) == 1:
                return candidates, 0

            clip_candidates = [
                ClipCandidate(
                    video_id=c["video_id"],
                    thumbnail_url=c["thumbnail_url"],
                    preview_urls=c["preview_urls"],
                )
                for c in candidates
            ]

            best_idx = await select_best_clip(
                candidates=clip_candidates,
                scene_description=scene_description,
                narration_text=narration_text,
                previous_clip_thumbnail=previous_thumbnail,
            )
            return candidates, best_idx

    return [], 0


async def stock_clip_sourcing_node(state: ShortsPipelineState) -> dict:
    """Search, evaluate with vision, and download the best stock clips."""
    logger.info("=== SHORTS: STOCK CLIP SOURCING ===")

    visual_assets = state.get("visual_assets", [])
    stock_segments = [a for a in visual_assets if a.asset_type == "stock_clip"]

    if not stock_segments:
        logger.info("No stock clips to source")
        return {"current_phase": "video_assembly", "messages": [AIMessage(content="No stock clips needed")]}

    pexels = get_pexels_service()
    pixabay = get_pixabay_service()
    history = get_shorts_history_service()
    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    previously_used = await history.get_used_clip_ids(source="pexels")
    used_video_ids = set(previously_used)
    logger.info(f"Loaded {len(previously_used)} previously used Pexels clip IDs")

    updated_assets = []
    fallback_to_image = []
    short_id = state.get("thread_id", "")
    topic = state.get("topic", "")
    previous_thumbnail: bytes | None = None
    money_shot_attributions: list[str] = []

    # Money-shot pass: pick the 1-2 payoff scenes and source the ACTUAL
    # Creative-Commons footage of the specific event (e.g. an octopus punching
    # a fish), vision-verified, instead of generic stock b-roll. Falls through
    # to the normal Pexels flow for everything else (and for money-shot scenes
    # where no CC clip verifies).
    money_shot_targets: dict[int, tuple[str, str, str]] = {}
    if settings.shorts_money_shot_enabled and stock_segments:
        try:
            from prolific.shorts.services.money_shot import identify_money_shots
            scene_texts = [a.script_text or a.search_query for a in stock_segments]
            picks = await identify_money_shots(
                topic, scene_texts, max_picks=settings.shorts_money_shot_max_per_video,
            )
            for p in picks:
                seg = stock_segments[p.scene_index]
                money_shot_targets[seg.sequence_number] = (
                    p.search_query, p.event_description, p.fallback_query,
                )
            if money_shot_targets:
                logger.info(f"Money-shot targets: {[(k, v[0]) for k, v in money_shot_targets.items()]}")
        except Exception as exc:
            logger.warning(f"Money-shot identification failed (non-fatal): {exc}")

    for asset in stock_segments:
        output_path = str(output_dir / f"clip_{asset.sequence_number:02d}.mp4")
        clip_source = "pexels"
        result = None
        video_id = None

        scene_desc = asset.search_query
        narration = asset.script_text or topic

        # Try the real-footage money shot first for targeted scenes.
        if asset.sequence_number in money_shot_targets:
            try:
                from prolific.shorts.services.money_shot import find_verified_cc_clip
                ms_query, ms_desc, ms_fallback = money_shot_targets[asset.sequence_number]
                ms = await find_verified_cc_clip(
                    event_query=ms_query, event_description=ms_desc,
                    output_dir=str(output_dir), filename=f"clip_{asset.sequence_number:02d}",
                    duration_seconds=asset.duration_seconds,
                    width=asset.width, height=asset.height,
                    fallback_query=ms_fallback,
                )
                if ms:
                    result = ms.file_path
                    clip_source = "money_shot_cc"
                    money_shot_attributions.append(
                        f'\n"{ms.title}" by {ms.creator} (CC BY, via YouTube)'
                    )
                    logger.info(f"[{asset.sequence_number}] MONEY SHOT ({ms_query}): {ms.file_path}")
            except Exception as exc:
                logger.warning(f"[{asset.sequence_number}] Money-shot attempt failed (non-fatal): {exc}")

        candidates, best_idx = (([], 0) if result else await _search_and_select(
            pexels, asset.search_query, used_video_ids,
            scene_desc, narration, previous_thumbnail,
        ))

        if candidates:
            chosen = candidates[best_idx]
            result, video_id = await pexels.download_and_trim(
                chosen, output_path, asset.duration_seconds,
                asset.width, asset.height, used_video_ids,
            )
            if result and chosen.get("thumbnail_url"):
                previous_thumbnail = await _download_thumbnail_bytes(chosen["thumbnail_url"])

        if not result and topic:
            topic_words = topic.split()[:3]
            query_words = asset.search_query.split()[:2]
            topic_query = " ".join(topic_words + query_words)
            logger.info(f"[{asset.sequence_number}] Trying topic fallback: '{topic_query}'")
            result, video_id = await pexels.fetch_clip(
                query=topic_query, output_path=output_path,
                duration=asset.duration_seconds, width=asset.width,
                height=asset.height, used_video_ids=used_video_ids, max_pages=1,
            )

        if not result and pixabay:
            logger.info(f"[{asset.sequence_number}] Trying Pixabay for: '{asset.search_query}'")
            clip_source = "pixabay"
            result, video_id = await pixabay.fetch_clip(
                query=asset.search_query, output_path=output_path,
                duration=asset.duration_seconds, width=asset.width,
                height=asset.height, used_video_ids=used_video_ids,
            )

        if video_id:
            await history.record_clip_usage(
                video_id=video_id, source=clip_source,
                search_query=asset.search_query, short_id=short_id,
            )

        if result:
            updated = VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="stock_clip",
                search_query=asset.search_query,
                file_path=result,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
                narration_start=asset.narration_start,
                narration_end=asset.narration_end,
                script_text=asset.script_text,
            )
            updated_assets.append(updated)
            logger.info(f"[{asset.sequence_number}] Stock clip: {asset.search_query} -> {result}")
        else:
            from prolific.shorts.nodes.image_generation import _search_web_images, _download_web_image
            img_dir = output_dir.parent / "images"
            img_dir.mkdir(parents=True, exist_ok=True)
            img_path = str(img_dir / f"web_fallback_{asset.sequence_number:02d}.png")

            file_path = None
            try:
                urls = await _search_web_images(asset.search_query)
                for url in urls[:5]:
                    if await _download_web_image(url, img_path):
                        file_path = img_path
                        break
            except Exception as e:
                logger.warning(f"Web image fallback failed: {e}")

            fallback = VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="web_image",
                search_query=asset.search_query,
                file_path=file_path,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
                script_text=asset.script_text,
            )
            fallback_to_image.append(fallback)
            status = "web image" if file_path else "no fallback"
            logger.warning(f"[{asset.sequence_number}] No stock clip for '{asset.search_query}', fell back to {status}")

    all_updated = updated_assets + fallback_to_image

    ms_count = len(money_shot_attributions)
    logger.info(
        f"Sourced {len(updated_assets)} stock clips ({ms_count} real-footage money shots), "
        f"{len(fallback_to_image)} fell back to web image"
    )

    out: dict = {
        "visual_assets": all_updated,
        "current_phase": "video_assembly",
        "messages": [AIMessage(content=f"Sourced {len(updated_assets)} clips ({ms_count} money shots, {len(fallback_to_image)} fallbacks)")],
    }
    if money_shot_attributions:
        # Credit the CC sources in the description (CC-BY requirement). The
        # metadata node appends state["attribution_texts"] verbatim.
        out["attribution_texts"] = ["\n\nFootage credits:"] + money_shot_attributions
    return out
