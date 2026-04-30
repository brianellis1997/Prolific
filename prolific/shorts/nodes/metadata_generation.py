"""Metadata generation node - creates YouTube Shorts title/description/tags."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import ShortsVideoMetadata
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class MetadataOutput(BaseModel):
    title: str
    description: str
    tags: list[str] = Field(default_factory=list)


async def metadata_generation_node(state: ShortsPipelineState) -> dict:
    """Generate YouTube Shorts metadata."""
    logger.info("=== SHORTS: METADATA GENERATION ===")

    script = state.get("script")
    topic = state.get("topic", "")

    if not script:
        return {"errors": ["No script for metadata"], "current_phase": "failed"}

    llm_service = get_llm_service()

    from prolific.shorts.prompts import METADATA_SYSTEM

    # Continuation: enforce Part 2 title marker if flagged
    continuation_instruction = ""
    is_continuation = state.get("is_intentional_continuation", False)
    parent_video_id = state.get("continues_video_id")
    if is_continuation and parent_video_id:
        try:
            from prolific.shorts.services.shorts_history import get_shorts_history_service
            history_service = get_shorts_history_service()
            parent = await history_service.get_short_by_id(parent_video_id)
            parent_title = parent.get("topic", "") if parent else ""
        except Exception as exc:
            logger.warning(f"Continuation parent lookup failed (non-fatal): {exc}")
            parent_title = ""

        if parent_title:
            continuation_instruction = (
                f"\n\nIMPORTANT — CONTINUATION SHORT: This builds on a previous short titled "
                f"'{parent_title}'. The title MUST include 'Part 2' or equivalent marker so "
                f"viewers know it's a continuation."
            )
        else:
            continuation_instruction = (
                "\n\nIMPORTANT — CONTINUATION SHORT: Title MUST include 'Part 2'."
            )

    prompt = METADATA_SYSTEM.format(
        topic=topic,
        script_text=script.full_text,
    ) + continuation_instruction

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the metadata now."),
        ],
        output_schema=MetadataOutput,
        tier="research",
        temperature=0.5,
    )

    # Belt-and-suspenders: enforce Part 2 marker on continuation shorts
    if is_continuation:
        title_lower = result.title.lower()
        markers = ["part 2", "part ii", "part two", "continued", "part 3", "part iii"]
        if not any(m in title_lower for m in markers):
            logger.warning(
                "Continuation flag set on short but title missing marker — appending"
            )
            result.title = f"{result.title} (Part 2)"

    description = result.description
    if "#Shorts" not in description and "#shorts" not in description:
        description = f"{description}\n\n#Shorts"

    source_urls = state.get("source_urls", [])
    if source_urls:
        sources_text = "\n".join(f"- {url}" for url in source_urls[:5])
        description = f"{description}\n\nSources:\n{sources_text}"

    attribution_texts = state.get("attribution_texts", [])
    if attribution_texts:
        description = f"{description}\n{''.join(attribution_texts)}"

    if "shorts" not in [t.lower() for t in result.tags]:
        result.tags.insert(0, "Shorts")

    niche = state.get("niche", "general")
    category_map = {
        "curiosity": "27",
        "sports": "17",
        "celebrity": "24",
        "twitch": "20",
        "general": "22",
    }

    metadata = ShortsVideoMetadata(
        title=result.title[:100],
        description=description,
        tags=result.tags[:15],
        category_id=category_map.get(niche, "22"),
    )

    logger.info(f"Title: {metadata.title}")
    logger.info(f"Tags: {', '.join(metadata.tags[:5])}...")

    thumbnail_path = _generate_thumbnail(state, script, topic)

    return {
        "video_metadata": metadata,
        "thumbnail_path": thumbnail_path,
        "current_phase": "youtube_upload",
        "messages": [AIMessage(content=f"Metadata: {metadata.title}")],
    }


def _generate_thumbnail(state, script, topic: str) -> str | None:
    """Generate thumbnail using hook text + best available visual."""
    try:
        from prolific.shorts.services.thumbnail import generate_thumbnail
        from prolific.core.config import settings
        from pathlib import Path

        thread_id = state.get("thread_id", "unknown")
        output_dir = Path(settings.shorts_output_dir) / thread_id
        output_dir.mkdir(parents=True, exist_ok=True)
        thumb_path = str(output_dir / "thumbnail.jpg")

        hook = script.hook if script and script.hook else topic

        bg_image = None
        visual_assets = state.get("visual_assets", [])
        for asset in visual_assets:
            if asset.file_path and asset.asset_type in ("web_image",) and Path(asset.file_path).exists():
                bg_image = asset.file_path
                break

        result = generate_thumbnail(
            output_path=thumb_path,
            hook_text=hook,
            background_image_path=bg_image,
        )
        return result
    except Exception as e:
        logger.warning(f"Thumbnail skipped: {e}")
        return None
