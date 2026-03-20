"""Image generation node - fetches web images for visual segments."""

import asyncio
import logging
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.schemas import VisualAsset
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)

MAX_CONCURRENT = 3


async def _search_web_images(query: str, max_results: int = 5) -> list[str]:
    """Search for real photos using Tavily image search."""
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        results = client.search(
            query=query,
            search_depth="basic",
            include_images=True,
            max_results=max_results,
        )
        image_urls = results.get("images", [])[:max_results]
        logger.info(f"Web image search '{query}': found {len(image_urls)} images")
        return image_urls
    except Exception as e:
        logger.warning(f"Web image search failed for '{query}': {e}")
        return []


async def _download_web_image(url: str, output_path: str) -> bool:
    """Download an image from URL and resize to 1080x1920 portrait with blurred background fill."""
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ProlificBot/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if not any(t in content_type for t in ["image/", "octet-stream"]):
                return False

            raw_path = output_path + ".raw"
            Path(raw_path).write_bytes(resp.content)

            try:
                from PIL import Image, ImageFilter
                img = Image.open(raw_path).convert("RGB")
                w, h = img.size
                target_w, target_h = 1080, 1920

                bg = img.resize((target_w, target_h), Image.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=30))

                img_ratio = w / h
                target_ratio = target_w / target_h
                if img_ratio > target_ratio:
                    scaled_w = target_w
                    scaled_h = int(target_w / img_ratio)
                else:
                    scaled_h = target_h
                    scaled_w = int(target_h * img_ratio)

                scaled_w = min(scaled_w, target_w)
                scaled_h = min(scaled_h, target_h)
                foreground = img.resize((scaled_w, scaled_h), Image.LANCZOS)

                x = (target_w - scaled_w) // 2
                y = (target_h - scaled_h) // 2
                bg.paste(foreground, (x, y))

                bg.save(output_path, "PNG")
                Path(raw_path).unlink(missing_ok=True)
            except ImportError:
                Path(raw_path).rename(output_path)

            logger.info(f"Downloaded web image: {output_path} ({len(resp.content) // 1024}KB)")
            return True
    except Exception as e:
        logger.warning(f"Failed to download {url}: {e}")
        return False


async def _verify_image_relevance(
    image_path: str, search_query: str, script_text: str
) -> tuple[bool, float]:
    """Check if a downloaded image matches what the narration is about."""
    try:
        import base64
        from pydantic import BaseModel, Field
        from prolific.services.llm import get_llm_service

        class ImageRelevanceCheck(BaseModel):
            matches_query: bool = False
            relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)

        img_data = base64.b64encode(Path(image_path).read_bytes()).decode()
        llm_service = get_llm_service()

        prompt = (
            f"Does this image show: '{search_query}'?\n"
            f"The narration at this point says: '{script_text[:200]}'\n"
            f"Score how relevant this image is to what's being discussed (0.0 to 1.0)."
        )

        result = await llm_service.invoke_with_image_structured(
            prompt=prompt,
            image_base64=img_data,
            output_schema=ImageRelevanceCheck,
            image_format="png",
        )
        return result.matches_query, result.relevance_score

    except Exception as e:
        logger.warning(f"Image verification failed: {e}")
        return True, 0.7


async def _fetch_web_image(
    asset: VisualAsset,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> VisualAsset:
    """Fetch a real photo from the web, verified for relevance."""
    async with semaphore:
        output_path = str(output_dir / f"web_{asset.sequence_number:02d}.png")
        try:
            image_urls = await _search_web_images(asset.search_query)
            for url in image_urls:
                if await _download_web_image(url, output_path):
                    if asset.script_text:
                        matches, score = await _verify_image_relevance(
                            output_path, asset.search_query, asset.script_text
                        )
                        if score < 0.4:
                            logger.info(f"[{asset.sequence_number}] Image rejected (score={score:.2f}), trying next")
                            continue
                        logger.info(f"[{asset.sequence_number}] Image verified (score={score:.2f}): {asset.search_query}")
                    else:
                        logger.info(f"[{asset.sequence_number}] Fetched web image for: {asset.search_query}")

                    return VisualAsset(
                        id=asset.id,
                        sequence_number=asset.sequence_number,
                        asset_type="web_image",
                        search_query=asset.search_query,
                        file_path=output_path,
                        width=asset.width,
                        height=asset.height,
                        duration_seconds=asset.duration_seconds,
                        ken_burns_direction=asset.ken_burns_direction,
                        script_text=asset.script_text,
                    )

            if asset.script_text:
                refined = await _get_refined_query(asset.search_query, asset.script_text)
                if refined and refined != asset.search_query:
                    logger.info(f"[{asset.sequence_number}] Retrying with refined query: '{refined}'")
                    retry_urls = await _search_web_images(refined)
                    for url in retry_urls:
                        if await _download_web_image(url, output_path):
                            return VisualAsset(
                                id=asset.id,
                                sequence_number=asset.sequence_number,
                                asset_type="web_image",
                                search_query=refined,
                                file_path=output_path,
                                width=asset.width,
                                height=asset.height,
                                duration_seconds=asset.duration_seconds,
                                ken_burns_direction=asset.ken_burns_direction,
                                script_text=asset.script_text,
                            )

            logger.warning(f"[{asset.sequence_number}] No suitable web images for: {asset.search_query}")
            return asset
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Web image fetch failed: {e}")
            return asset


async def _get_refined_query(original_query: str, script_text: str) -> str:
    """Use LLM to suggest a better image search query."""
    try:
        from prolific.services.llm import get_llm_service
        llm_service = get_llm_service()
        response = await llm_service.invoke(
            messages=[
                {"role": "system", "content": "Suggest a better 3-5 word image search query."},
                {"role": "user", "content": (
                    f"The search '{original_query}' returned irrelevant images. "
                    f"The narration says: '{script_text[:200]}'. "
                    f"Suggest a better search query to find a relevant photo. "
                    f"Return ONLY the query, nothing else."
                )},
            ],
            tier="research",
            temperature=0.3,
        )
        refined = response.strip().strip('"').strip("'")
        return refined[:60]
    except Exception:
        return original_query


async def image_generation_node(state: ShortsPipelineState) -> dict:
    """Fetch web images for visual segments. AI image generation is disabled for Shorts."""
    logger.info("=== SHORTS: IMAGE GENERATION ===")

    visual_assets = state.get("visual_assets", [])
    web_segments = [a for a in visual_assets if a.asset_type == "web_image" and not a.file_path]

    if not web_segments:
        logger.info("No web images to fetch")
        return {"current_phase": "tts_generation", "messages": [AIMessage(content="No web images needed")]}

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    logger.info(f"Fetching {len(web_segments)} web images")
    tasks = [_fetch_web_image(asset, output_dir, semaphore) for asset in web_segments]
    results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r.file_path)
    failed = len(results) - ok
    if failed:
        logger.warning(f"{failed} web image(s) failed to download — those segments will be skipped in assembly")
    logger.info(f"Image phase complete: {ok}/{len(results)} web images fetched")

    return {
        "visual_assets": results,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Web images: {ok}/{len(results)} fetched")],
    }
