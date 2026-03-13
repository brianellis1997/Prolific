"""Script writing node - creates a 75-90 word short-form script."""

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
    """Write a 75-90 word script for the short."""
    logger.info("=== SHORTS: SCRIPT WRITING ===")
    logger.info(f"Topic: {state['topic']}")

    llm_service = get_llm_service()

    from prolific.shorts.prompts import SCRIPT_WRITING_SYSTEM

    hook_angle = ""
    for msg in reversed(state.get("messages", [])):
        if hasattr(msg, "content") and "Hook:" in msg.content:
            hook_angle = msg.content.split("Hook:")[-1].strip()
            break

    prompt = SCRIPT_WRITING_SYSTEM.format(
        topic=state["topic"],
        hook_angle=hook_angle or state["topic"],
    )

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
