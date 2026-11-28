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


TITLE_RULES = (
    "\n\nTITLE RULES: The title must stand alone. Never add 'Part 2', 'Part II' or any sequel marker, "
    "because a viewer in the Shorts feed has not seen an earlier short. The title must also be true to the "
    "script: curiosity is good, but never claim more than the script says (a viewer called 'White Chocolate "
    "is a Lie' clickbait when the script only said it has no cocoa solids)."
)

_SEQUEL = r"part\s*(?:2|ii|two|3|iii|three)"


def strip_sequel_marker(title: str) -> str:
    import re

    out = re.sub(rf"\s*[\(\[]\s*{_SEQUEL}\s*[\)\]]", "", title, flags=re.I)
    out = re.sub(rf"^\s*{_SEQUEL}\s*[:\-]\s*", "", out, flags=re.I)
    out = re.sub(rf"\s*[:\-]?\s*\b{_SEQUEL}\s*$", "", out, flags=re.I)
    return out.strip() or title


async def metadata_generation_node(state: ShortsPipelineState) -> dict:
    """Generate YouTube Shorts metadata."""
    logger.info("=== SHORTS: METADATA GENERATION ===")

    script = state.get("script")
    topic = state.get("topic", "")

    if not script:
        return {"errors": ["No script for metadata"], "current_phase": "failed"}

    llm_service = get_llm_service()

    from prolific.shorts.prompts import METADATA_SYSTEM

    prompt = METADATA_SYSTEM.format(
        topic=topic,
        script_text=script.full_text,
    ) + TITLE_RULES

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Generate the metadata now."),
        ],
        output_schema=MetadataOutput,
        tier="research",
        temperature=0.5,
    )
    standalone = strip_sequel_marker(result.title)
    if standalone != result.title:
        logger.info(f"Removed a sequel marker from the title: {result.title!r} -> {standalone!r}")
        result.title = standalone

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

    return {
        "video_metadata": metadata,
        "current_phase": "youtube_upload",
        "messages": [AIMessage(content=f"Metadata: {metadata.title}")],
    }
