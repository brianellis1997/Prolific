"""Vision-based clip selection — scores stock footage candidates against scene requirements.

A human editor would browse thumbnails, check relevance to the narration, and ensure
visual flow with adjacent clips. This service automates that process using Gemini vision.
"""

import asyncio
import base64
import logging

import httpx
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class ClipCandidate(BaseModel):
    video_id: str
    thumbnail_url: str = ""
    preview_urls: list[str] = Field(default_factory=list)
    best_file: dict = Field(default_factory=dict)
    pexels_data: dict = Field(default_factory=dict)


class ClipScore(BaseModel):
    best_index: int = 0
    relevance_scores: list[float] = Field(default_factory=list)
    reasoning: str = ""


async def _download_thumbnail(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.warning(f"Failed to download thumbnail: {e}")
        return None


async def select_best_clip(
    candidates: list[ClipCandidate],
    scene_description: str,
    narration_text: str,
    previous_clip_thumbnail: bytes | None = None,
) -> int:
    """Use vision model to pick the best clip from candidates.

    Downloads thumbnails for each candidate, sends them to Gemini with the
    scene description, and returns the index of the best match.

    Args:
        candidates: List of clip candidates with thumbnail URLs
        scene_description: What this shot should show (from clip director)
        narration_text: What's being said during this clip
        previous_clip_thumbnail: Thumbnail bytes of the previous clip (for flow checking)

    Returns:
        Index of the best candidate (0-based)
    """
    if not candidates:
        return 0
    if len(candidates) == 1:
        return 0

    thumbnail_tasks = []
    for c in candidates:
        url = c.thumbnail_url or (c.preview_urls[0] if c.preview_urls else "")
        if url:
            thumbnail_tasks.append(_download_thumbnail(url))
        else:
            thumbnail_tasks.append(asyncio.coroutine(lambda: None)())

    thumbnails = await asyncio.gather(*thumbnail_tasks)

    valid_thumbs = [(i, t) for i, t in enumerate(thumbnails) if t]
    if len(valid_thumbs) <= 1:
        return valid_thumbs[0][0] if valid_thumbs else 0

    image_parts = []
    for idx, (i, thumb_bytes) in enumerate(valid_thumbs):
        b64 = base64.b64encode(thumb_bytes).decode()
        image_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
        image_parts.append({
            "type": "text",
            "text": f"[Clip {idx + 1}]",
        })

    flow_context = ""
    if previous_clip_thumbnail:
        prev_b64 = base64.b64encode(previous_clip_thumbnail).decode()
        image_parts.insert(0, {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{prev_b64}"},
        })
        image_parts.insert(1, {
            "type": "text",
            "text": "[Previous clip — the selected clip should flow visually from this]",
        })
        flow_context = (
            "\nVISUAL FLOW: The selected clip will play immediately after the 'Previous clip' shown above. "
            "Prefer clips that share a similar color palette, setting, or visual tone with the previous clip. "
            "Avoid jarring transitions (e.g., underwater -> office, dark -> bright white)."
        )

    prompt = (
        f"You are a video editor selecting the best stock footage clip for a YouTube Short.\n\n"
        f"SCENE NEEDED: {scene_description}\n"
        f"NARRATION AT THIS MOMENT: \"{narration_text}\"\n"
        f"{flow_context}\n\n"
        f"I'm showing you {len(valid_thumbs)} candidate clip thumbnails. "
        f"Pick the one that BEST matches what the narration is describing AND flows well visually.\n\n"
        f"Score each clip 0.0-1.0 on relevance to the scene/narration. "
        f"Return the 1-based index of the best clip."
    )

    from langchain_core.messages import HumanMessage

    message = HumanMessage(content=[{"type": "text", "text": prompt}] + image_parts)

    try:
        llm_service = get_llm_service()
        llm = llm_service.get_llm("vision", temperature=0.2)
        from prolific.services.usage_tracker import LLMUsageCallbackHandler
        handler = LLMUsageCallbackHandler(model_name=llm_service.get_model_name("vision"))
        structured_llm = llm.with_structured_output(ClipScore)
        result = await structured_llm.ainvoke(
            llm_service._inject_date_context([message]),
            config={"callbacks": [handler]},
        )

        best_1indexed = result.best_index
        if 1 <= best_1indexed <= len(valid_thumbs):
            chosen_original_idx = valid_thumbs[best_1indexed - 1][0]
        else:
            chosen_original_idx = valid_thumbs[0][0]

        scores_str = ", ".join(f"{s:.1f}" for s in (result.relevance_scores or []))
        logger.info(
            f"  Vision selected clip {best_1indexed}/{len(valid_thumbs)} "
            f"(scores: [{scores_str}]) — {result.reasoning[:80]}"
        )
        return chosen_original_idx

    except Exception as e:
        logger.warning(f"Vision clip selection failed: {e} — using first candidate")
        return 0
