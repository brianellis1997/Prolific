"""Script writing node - writes narration prose section by section."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.prompts import (
    CHANNEL_PLUG_INSTRUCTION,
    CHANNEL_PLUG_NONE,
    MODE_STYLE_BLOCKS,
    SCRIPT_WRITING_CONTINUATION,
    SCRIPT_WRITING_SYSTEM,
)
from prolific.youtube.schemas import ScriptSection
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)

WORDS_PER_MINUTE_NARRATION = 150


async def script_writing_node(state: YouTubePipelineState) -> dict:
    """Write the narration script section by section."""
    logger.info("=== SCRIPT WRITING ===")

    topic = state["topic"]
    sections = list(state["script_sections"])
    target_words = settings.youtube_target_word_count
    words_per_section = target_words // max(len(sections), 1)
    total_sections = len(sections)
    content_mode = state.get("content_mode") or "BIOGRAPHY"
    content_mode_style = MODE_STYLE_BLOCKS.get(content_mode, "")

    logger.info(f"Writing {total_sections} sections, ~{words_per_section} words each")

    llm_service = get_llm_service()
    updated_sections = []
    previous_ending = ""
    total_word_count = 0

    for i, section in enumerate(sections):
        logger.info(f"[{i + 1}/{total_sections}] Writing: {section.title}")

        key_points_str = "\n".join(f"- {kp}" for kp in section.key_points)

        if previous_ending:
            previous_context = SCRIPT_WRITING_CONTINUATION.format(
                previous_ending=previous_ending
            )
        else:
            previous_context = "This is the opening of the video. Begin gently and set the scene."

        is_plug_section = (i == 0)
        channel_plug_instruction = CHANNEL_PLUG_INSTRUCTION if is_plug_section else CHANNEL_PLUG_NONE

        prompt = SCRIPT_WRITING_SYSTEM.format(
            topic=topic,
            section_title=section.title,
            section_num=i + 1,
            total_sections=total_sections,
            key_points=key_points_str,
            previous_context=previous_context,
            content_mode_style=content_mode_style,
            target_words=words_per_section,
            channel_plug_instruction=channel_plug_instruction,
        )

        response = await llm_service.invoke(
            messages=[
                SystemMessage(content=prompt),
                HumanMessage(content="Write the narration now."),
            ],
            tier="research",
            temperature=0.7,
            max_tokens=8192,
        )

        content = response.content.strip()
        word_count = len(content.split())
        total_word_count += word_count

        previous_ending = content[-500:] if len(content) > 500 else content

        updated_section = ScriptSection(
            id=section.id,
            section_number=section.section_number,
            title=section.title,
            key_points=section.key_points,
            content=content,
            word_count=word_count,
            estimated_duration_minutes=word_count / WORDS_PER_MINUTE_NARRATION,
        )
        updated_sections.append(updated_section)

        logger.info(f"  Written {word_count} words ({total_word_count} total)")

    logger.info(f"Script complete: {total_word_count} words, "
                f"~{total_word_count / WORDS_PER_MINUTE_NARRATION / 60:.1f} hours")

    thread_id = state["thread_id"]
    script_path = Path(settings.youtube_output_dir) / thread_id / "script.txt"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    with open(script_path, "w") as f:
        for section in updated_sections:
            f.write(section.content)
            f.write("\n\n")
    logger.info(f"Script saved to {script_path}")

    return {
        "script_sections": updated_sections,
        "total_script_word_count": total_word_count,
        "current_phase": "image_planning",
        "messages": [AIMessage(content=f"Script written: {total_word_count} words")],
    }
