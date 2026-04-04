"""Script writing node - creates mode-aware short-form scripts."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.schemas import ShortScript
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class ScriptOutput(BaseModel):
    hook: str
    setup: str
    value_body: str
    cta_loop: str
    visual_suggestions: list[str] = Field(default_factory=list)


async def script_writing_node(state: ShortsPipelineState) -> dict:
    """Write a 75-90 word script, adapting to content mode."""
    logger.info("=== SHORTS: SCRIPT WRITING ===")
    logger.info(f"Topic: {state['topic']}")

    content_mode = state.get("content_mode", "news_commentary")
    logger.info(f"Content mode: {content_mode}")

    llm_service = get_llm_service()

    hook_angle = ""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "Hook:" in msg.content:
            hook_angle = msg.content.split("Hook:")[-1].strip()
            break

    prompt = _build_prompt(state, content_mode, hook_angle)

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Write the script now."),
        ],
        output_schema=ScriptOutput,
        tier="research",
        temperature=0.7,
    )

    full_text = f"{result.hook} {result.setup} {result.value_body} {result.cta_loop}".strip()
    word_count = len(full_text.split())

    script = ShortScript(
        hook=result.hook,
        setup=result.setup,
        value_body=result.value_body,
        cta_loop=result.cta_loop,
        full_text=full_text,
        word_count=word_count,
        visual_suggestions=result.visual_suggestions[:10],
    )

    logger.info(f"Script written: {word_count} words")
    logger.info(f"Hook: {result.hook[:80]}...")

    return {
        "script": script,
        "current_phase": "visual_planning",
        "messages": [AIMessage(content=f"Script written: {word_count} words")],
    }


def _build_prompt(state: dict, content_mode: str, hook_angle: str) -> str:
    topic = state.get("topic", "")

    if content_mode == "clip_compilation":
        from prolific.shorts.prompts import COMPILATION_SCRIPT_SYSTEM
        compilation_items = state.get("compilation_items", [])
        items_str = "\n".join(f"{i+1}. {item}" for i, item in enumerate(compilation_items))
        return COMPILATION_SCRIPT_SYSTEM.format(
            topic=topic,
            compilation_items=items_str or "(no items researched)",
            hook_angle=hook_angle or topic,
        )

    if content_mode == "clip_reaction":
        from prolific.shorts.prompts import CLIP_REACTION_SCRIPT_SYSTEM
        understandings = state.get("clip_content_understanding") or []
        u = understandings[0] if understandings else None

        if u and (u.visual_analysis or u.transcript):
            va = u.visual_analysis
            visual_analysis = ""
            if va:
                parts = []
                if va.people_visible:
                    parts.append(f"People visible: {', '.join(va.people_visible)}")
                if va.actions_described:
                    parts.append(f"Actions: {', '.join(va.actions_described)}")
                if va.setting:
                    parts.append(f"Setting: {va.setting}")
                if va.visual_summary:
                    parts.append(f"Summary: {va.visual_summary}")
                visual_analysis = "\n".join(parts)

            clip_duration = u.clip_duration_seconds or 28
            target_words = int(clip_duration * 2.5)
            target_words = max(40, min(target_words, 85))

            return CLIP_REACTION_SCRIPT_SYSTEM.format(
                topic=topic,
                visual_analysis=visual_analysis or "(no visual analysis available)",
                transcript=u.transcript[:500] if u.transcript else "(no transcript available)",
                key_moments="\n".join(f"- {m}" for m in u.key_moments) if u.key_moments else "(none identified)",
                clip_duration=f"{clip_duration:.0f}",
                target_words=str(target_words),
                hook_angle=hook_angle or topic,
            )

        from prolific.shorts.prompts import SCRIPT_WRITING_SYSTEM
        return SCRIPT_WRITING_SYSTEM.format(topic=topic, hook_angle=hook_angle or topic)

    from prolific.shorts.nodes.topic_selection import _is_ai_video_run
    if _is_ai_video_run():
        from prolific.shorts.prompts import AI_VIDEO_SCRIPT_SYSTEM
        base_prompt = AI_VIDEO_SCRIPT_SYSTEM.format(
            topic=topic,
            hook_angle=hook_angle or topic,
        )
    else:
        from prolific.shorts.prompts import SCRIPT_WRITING_SYSTEM
        base_prompt = SCRIPT_WRITING_SYSTEM.format(
            topic=topic,
            hook_angle=hook_angle or topic,
        )

    if content_mode == "niche_drama":
        understandings = state.get("clip_content_understanding") or []
        if understandings:
            clip_context_parts = []
            for i, u in enumerate(understandings):
                parts = [f"\nSOURCE CLIP {i+1} ({u.clip_duration_seconds:.0f}s):"]
                if u.content_summary:
                    parts.append(f"  Content: {u.content_summary}")
                if u.visual_analysis and u.visual_analysis.people_visible:
                    parts.append(f"  People visible: {', '.join(u.visual_analysis.people_visible)}")
                if u.key_moments:
                    parts.append(f"  Moments: {'; '.join(u.key_moments[:3])}")
                clip_context_parts.append("\n".join(parts))
            base_prompt += (
                "\n\nAVAILABLE CLIP CONTENT (only reference things confirmed here):"
                + "".join(clip_context_parts)
                + "\n\nOnly mention people/events that are confirmed in the clips above."
            )

    return base_prompt
