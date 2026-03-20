"""Compilation research node - researches list items for compilation-style shorts."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.services.llm import get_llm_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class CompilationResearch(BaseModel):
    items: list[str] = Field(default_factory=list)
    item_facts: list[str] = Field(default_factory=list)


COMPILATION_RESEARCH_PROMPT = """You are a content researcher. The user wants to make a
YouTube Short about: {topic}

Research and provide a ranked list of items for this compilation. Use your knowledge and
the search results below to create an accurate, engaging list.

SEARCH RESULTS:
{search_context}

Return:
- items: A list of 3-5 items in order (e.g. ["John Ross - 4.22 seconds", "Chris Johnson - 4.24 seconds", ...])
- item_facts: A matching list of 1-sentence fun facts for each item

Keep items concise (name + key stat/detail). Order for maximum dramatic effect
(save the most impressive for last if counting up, or lead with it if counting down)."""


async def compilation_research_node(state: ShortsPipelineState) -> dict:
    """Research list items for a compilation-style short."""
    logger.info("=== SHORTS: COMPILATION RESEARCH ===")

    topic = state.get("topic", "")
    llm_service = get_llm_service()

    search_context = ""
    try:
        from prolific.services.web_search import get_web_search_service
        search_service = get_web_search_service()
        results = await search_service.search(
            query=topic,
            max_results=5,
            search_depth="basic",
        )
        if results:
            search_context = "\n".join(
                f"- {r.title}: {r.snippet[:200]}" for r in results
            )
    except Exception as e:
        logger.warning(f"Compilation web search failed: {e}")

    prompt = COMPILATION_RESEARCH_PROMPT.format(
        topic=topic,
        search_context=search_context or "(no search results available)",
    )

    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=prompt),
            HumanMessage(content="Research the list items now."),
        ],
        output_schema=CompilationResearch,
        tier="research",
        temperature=0.5,
    )

    items = result.items or []
    logger.info(f"Researched {len(items)} compilation items: {items}")

    return {
        "compilation_items": items,
        "current_phase": "clip_sourcing",
        "messages": [AIMessage(content=f"Researched {len(items)} compilation items")],
    }
