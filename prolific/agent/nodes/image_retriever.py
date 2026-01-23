"""Image Retriever node for fetching images from the web.

The Image Retriever Agent searches for and retrieves relevant images
based on VisualIntent specifications.
"""

import base64
import hashlib
import logging
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import VisualAsset, VisualIntent, VisualType
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class ImageCandidate(BaseModel):
    """A candidate image from search results."""

    url: str
    title: str
    source_url: str
    thumbnail_url: str | None = None


class ImageSearchResult(BaseModel):
    """Results from image search."""

    candidates: list[ImageCandidate] = Field(default_factory=list)


class ImageEvaluation(BaseModel):
    """Evaluation of an image's suitability."""

    is_suitable: bool
    relevance_score: float = Field(ge=0.0, le=1.0)
    quality_score: float = Field(ge=0.0, le=1.0)
    caption: str = ""
    alt_text: str = ""
    concerns: list[str] = Field(default_factory=list)


IMAGE_EVAL_PROMPT = """You are evaluating whether this image is suitable for inclusion in written content.

Visual Intent (what we're looking for):
- Description: {description}
- Purpose: {purpose}

Image Metadata:
- Title: {title}
- Source: {source_url}

Look at the image and evaluate:
1. is_suitable: Is this image appropriate, relevant, and professional?
2. relevance_score: 0.0-1.0, how well does it match what we need?
3. quality_score: 0.0-1.0, image clarity, resolution, composition
4. caption: A suitable caption for this image in the content
5. alt_text: Accessible description for screen readers
6. concerns: Any issues (watermarks, low quality, irrelevant, inappropriate)

Reject images with:
- Stock photo watermarks
- Low resolution or blurry content
- Irrelevant subject matter
- Inappropriate or unprofessional content
"""


async def search_images(query: str, max_results: int = 5) -> list[ImageCandidate]:
    """Search for images using Tavily web search.

    Searches for image-related content and extracts image URLs from results.
    For production, consider dedicated image APIs (Unsplash, Pexels, Bing Image).

    Args:
        query: Search query
        max_results: Maximum number of results

    Returns:
        List of ImageCandidate objects
    """
    from prolific.core.config import settings

    logger.info(f"Image search for: {query}")

    if not settings.tavily_api_key:
        logger.warning("No Tavily API key configured for image search")
        return []

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=settings.tavily_api_key)

        results = client.search(
            query=f"{query} image",
            search_depth="basic",
            include_images=True,
            max_results=max_results * 2,
        )

        candidates = []

        if results.get("images"):
            for img_url in results["images"][:max_results]:
                candidates.append(
                    ImageCandidate(
                        url=img_url,
                        title=query,
                        source_url=img_url,
                        thumbnail_url=img_url,
                    )
                )

        for result in results.get("results", []):
            if len(candidates) >= max_results:
                break

            url = result.get("url", "")
            if any(ext in url.lower() for ext in [".png", ".jpg", ".jpeg", ".webp", ".gif"]):
                candidates.append(
                    ImageCandidate(
                        url=url,
                        title=result.get("title", query),
                        source_url=result.get("url", ""),
                        thumbnail_url=url,
                    )
                )

        logger.info(f"Found {len(candidates)} image candidates for: {query}")
        return candidates[:max_results]

    except Exception as e:
        logger.warning(f"Image search failed: {e}")
        return []


async def download_image(url: str) -> tuple[bytes | None, str]:
    """Download an image from URL.

    Args:
        url: Image URL

    Returns:
        Tuple of (image_bytes, format) or (None, "") on failure
    """
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ProlificBot/1.0)"}
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "png" in content_type:
                fmt = "png"
            elif "jpeg" in content_type or "jpg" in content_type:
                fmt = "jpg"
            elif "webp" in content_type:
                fmt = "webp"
            else:
                fmt = "png"

            return response.content, fmt

    except Exception as e:
        logger.warning(f"Failed to download image from {url}: {e}")
        return None, ""


async def image_retriever_node(state: ContentGenerationState) -> dict:
    """Retrieve images from the web for image-type visual intents.

    This node:
    1. Filters visual intents for web image types
    2. Searches for relevant images
    3. Evaluates and downloads suitable images
    4. Creates VisualAsset artifacts

    Args:
        state: Current workflow state

    Returns:
        Dict with visual_assets to merge into state
    """
    logger.info("=== IMAGE RETRIEVAL PHASE ===")

    visual_intents = state.get("visual_intents", [])
    existing_assets = {str(a.intent_id) for a in state.get("visual_assets", [])}

    image_intents = [
        intent for intent in visual_intents
        if intent.visual_type == VisualType.IMAGE_WEB
        and str(intent.id) not in existing_assets
    ]

    if not image_intents:
        logger.info("No image intents to retrieve")
        return {
            "messages": [AIMessage(content="No images to retrieve.")],
        }

    logger.info(f"Retrieving {len(image_intents)} images")

    llm_service = get_llm_service()
    visual_assets = []

    for intent in image_intents:
        try:
            all_candidates = []
            for query in intent.search_queries[:3]:
                candidates = await search_images(query)
                all_candidates.extend(candidates)

            if not all_candidates:
                logger.info(f"No image candidates found for intent {intent.id}")
                continue

            for candidate in all_candidates[:5]:
                image_bytes, fmt = await download_image(candidate.url)
                if not image_bytes:
                    logger.info(f"Could not download image: {candidate.url}")
                    continue

                image_b64 = base64.b64encode(image_bytes).decode("utf-8")

                eval_prompt = IMAGE_EVAL_PROMPT.format(
                    description=intent.description,
                    purpose=intent.purpose.value,
                    title=candidate.title,
                    source_url=candidate.source_url,
                )

                try:
                    evaluation = await llm_service.invoke_with_image_structured(
                        prompt=eval_prompt,
                        image_base64=image_b64,
                        output_schema=ImageEvaluation,
                        image_format=fmt,
                        tier="vision",
                        temperature=0.1,
                    )
                except Exception as e:
                    logger.warning(f"Image evaluation failed: {e}")
                    continue

                if not evaluation.is_suitable or evaluation.relevance_score < 0.6:
                    logger.info(f"Image not suitable: {candidate.url} (score={evaluation.relevance_score})")
                    continue

                content_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

                with tempfile.NamedTemporaryFile(
                    suffix=f".{fmt}", delete=False
                ) as tmp:
                    tmp.write(image_bytes)
                    file_path = tmp.name

                asset = VisualAsset(
                    id=uuid4(),
                    intent_id=intent.id,
                    visual_type=VisualType.IMAGE_WEB,
                    source="web",
                    file_path=file_path,
                    url=candidate.url,
                    base64_data=image_b64,
                    caption=evaluation.caption,
                    alt_text=evaluation.alt_text,
                    format=fmt,
                    quality_score=evaluation.quality_score,
                    relevance_score=evaluation.relevance_score,
                    provenance={
                        "source_url": candidate.source_url,
                        "title": candidate.title,
                        "content_hash": content_hash,
                    },
                )
                visual_assets.append(asset)
                logger.info(f"Retrieved image for intent {intent.id}")
                break

        except Exception as e:
            logger.error(f"Failed to retrieve image for intent {intent.id}: {e}")

    logger.info(f"Image retrieval complete: {len(visual_assets)} images retrieved")

    return {
        "visual_assets": visual_assets,
        "messages": [
            AIMessage(content=f"Retrieved {len(visual_assets)} images.")
        ],
    }
