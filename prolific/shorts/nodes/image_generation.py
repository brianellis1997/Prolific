"""Image generation node - generates AI images and fetches web images."""

import asyncio
import logging
from pathlib import Path

import httpx
from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.services.image_gen import ImageGenService
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
    """Download an image from URL and resize to 1080x1920 portrait. Returns True on success."""
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
                logger.info(f"Not an image content-type: {content_type}")
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


async def _fetch_web_image(
    asset: VisualAsset,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> VisualAsset:
    """Fetch a real photo from the web for a web_image asset."""
    async with semaphore:
        output_path = str(output_dir / f"web_{asset.sequence_number:02d}.png")
        try:
            image_urls = await _search_web_images(asset.search_query)
            for url in image_urls:
                if await _download_web_image(url, output_path):
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
                    )
            logger.warning(f"[{asset.sequence_number}] No web images found, will fall back to AI")
            return asset
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Web image fetch failed: {e}")
            return asset


async def _generate_one(
    service: ImageGenService,
    asset: VisualAsset,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
    style: str = "",
) -> VisualAsset:
    """Generate a single AI image for a visual asset."""
    async with semaphore:
        output_path = str(output_dir / f"image_{asset.sequence_number:02d}.png")
        try:
            style_prefix = (style or settings.shorts_image_style) + ". "
            prompt = asset.image_prompt
            if not prompt and asset.search_query:
                prompt = f"Photo-realistic image of: {asset.search_query}"
            await service.generate_image(
                prompt=prompt,
                output_path=output_path,
                style_prefix=style_prefix,
            )
            logger.info(f"[{asset.sequence_number}] Generated AI image")
            return VisualAsset(
                id=asset.id,
                sequence_number=asset.sequence_number,
                asset_type="ai_image",
                image_prompt=asset.image_prompt,
                file_path=output_path,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                ken_burns_direction=asset.ken_burns_direction,
            )
        except Exception as e:
            logger.error(f"[{asset.sequence_number}] Image generation failed: {e}")
            return asset


NEWS_IMAGE_STYLE = "photojournalistic, realistic photo, news photography style, high detail, 9:16 portrait composition"
FACT_IMAGE_STYLE = "bold digital art, dramatic lighting, vibrant colors, 9:16 portrait composition"


async def image_generation_node(state: ShortsPipelineState) -> dict:
    """Generate AI images and fetch web images for segments that need them."""
    logger.info("=== SHORTS: IMAGE GENERATION ===")

    visual_assets = state.get("visual_assets", [])
    web_segments = [a for a in visual_assets if a.asset_type == "web_image" and not a.file_path]
    ai_segments = [a for a in visual_assets if a.asset_type == "ai_image" and not a.file_path]

    if not web_segments and not ai_segments:
        logger.info("No images to generate or fetch")
        return {"current_phase": "tts_generation", "messages": [AIMessage(content="No images needed")]}

    topic_type = state.get("topic_type", "")
    if topic_type == "breaking_news":
        image_style = NEWS_IMAGE_STYLE
        logger.info("Using photorealistic style for breaking news topic")
    else:
        image_style = settings.shorts_image_style or FACT_IMAGE_STYLE

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    all_results = []

    if web_segments:
        logger.info(f"Fetching {len(web_segments)} web images")
        web_tasks = [_fetch_web_image(asset, output_dir, semaphore) for asset in web_segments]
        web_results = await asyncio.gather(*web_tasks)

        fallback_to_ai = []
        for r in web_results:
            if r.file_path:
                all_results.append(r)
            else:
                r.asset_type = "ai_image"
                if not r.image_prompt:
                    r.image_prompt = f"Photo-realistic image of: {r.search_query}"
                fallback_to_ai.append(r)

        if fallback_to_ai:
            logger.info(f"{len(fallback_to_ai)} web images failed, falling back to AI generation")
            ai_segments.extend(fallback_to_ai)

    if ai_segments:
        logger.info(f"Generating {len(ai_segments)} AI images")
        service = ImageGenService(model=settings.shorts_image_model)
        ai_tasks = [_generate_one(service, asset, output_dir, semaphore, style=image_style) for asset in ai_segments]
        ai_results = await asyncio.gather(*ai_tasks)
        all_results.extend(ai_results)

    generated_count = sum(1 for r in all_results if r.file_path)
    web_ok = sum(1 for r in all_results if r.asset_type == "web_image" and r.file_path)
    ai_ok = sum(1 for r in all_results if r.asset_type == "ai_image" and r.file_path)
    logger.info(f"Image phase complete: {web_ok} web + {ai_ok} AI = {generated_count} total")

    return {
        "visual_assets": all_results,
        "current_phase": "tts_generation",
        "messages": [AIMessage(content=f"Images: {web_ok} web + {ai_ok} AI = {generated_count} total")],
    }
