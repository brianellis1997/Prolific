"""Topic selection node - finds trending news or mind-blowing facts."""

import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.shorts.services.shorts_history import get_shorts_history_service
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


class ShortTopicCandidate(BaseModel):
    topic: str
    topic_type: str = "mind_blowing_fact"
    hook_angle: str = ""
    virality_reason: str = ""
    visual_keywords: list[str] = Field(default_factory=list)
    trending_tie_in: str = ""


class ShortTopicBrainstorm(BaseModel):
    candidates: list[ShortTopicCandidate]


class ShortTopicSelection(BaseModel):
    chosen_index: int
    rationale: str


async def _get_trending_context() -> str:
    try:
        from prolific.services.web_search import get_web_search_service
        search_service = get_web_search_service()

        queries = [
            "trending viral news today celebrity gossip drama",
            "shocking news today what everyone is talking about",
            "viral social media moment today controversy",
        ]
        all_headlines = []
        for query in queries:
            results = await search_service.search(
                query=query,
                max_results=5,
                search_depth="basic",
            )
            for r in results or []:
                all_headlines.append(f"- {r.title}: {r.snippet[:150]}")

        seen = set()
        unique = []
        for h in all_headlines:
            key = h[:60]
            if key not in seen:
                seen.add(key)
                unique.append(h)

        logger.info(f"Fetched {len(unique)} trending headlines")
        return "\n".join(unique[:15])

    except Exception as e:
        logger.warning(f"Trending news fetch failed (non-fatal): {e}")
        return ""


async def topic_selection_node(state: ShortsPipelineState) -> dict:
    """Select a topic for the short-form video."""
    logger.info("=== SHORTS: TOPIC SELECTION ===")

    llm_service = get_llm_service()
    history_service = get_shorts_history_service()

    past_topics = await history_service.get_past_topics(hours=48)
    past_topics_str = "\n".join(f"- {t}" for t in past_topics) if past_topics else "(none yet)"

    trending_context = await _get_trending_context()

    from prolific.shorts.prompts import TOPIC_BRAINSTORM_SYSTEM

    brainstorm_prompt = TOPIC_BRAINSTORM_SYSTEM.format(
        num_candidates=8,
        trending_context=trending_context if trending_context else "(no trending data available)",
        past_topics=past_topics_str,
    )

    brainstorm_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=brainstorm_prompt),
            HumanMessage(content="Generate topic candidates now."),
        ],
        output_schema=ShortTopicBrainstorm,
        tier="research",
        temperature=0.9,
    )

    candidates = brainstorm_result.candidates
    logger.info(f"Brainstormed {len(candidates)} short topic candidates")

    if not candidates:
        return {
            "errors": ["No topic candidates generated"],
            "current_phase": "failed",
        }

    from prolific.shorts.prompts import TOPIC_SELECT_SYSTEM

    candidates_str = "\n".join(
        f"[{i}] {c.topic} ({c.topic_type}) - {c.hook_angle}"
        + (f" [TRENDING: {c.trending_tie_in}]" if c.trending_tie_in else "")
        for i, c in enumerate(candidates)
    )

    selection_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=TOPIC_SELECT_SYSTEM),
            HumanMessage(content=f"Candidates:\n{candidates_str}\n\nSelect the best one."),
        ],
        output_schema=ShortTopicSelection,
        tier="research",
        temperature=0.3,
    )

    chosen_idx = max(0, min(selection_result.chosen_index, len(candidates) - 1))
    chosen = candidates[chosen_idx]

    logger.info(f"Selected short topic: {chosen.topic}")
    logger.info(f"Type: {chosen.topic_type}")
    logger.info(f"Hook: {chosen.hook_angle}")

    return {
        "topic": chosen.topic,
        "topic_type": chosen.topic_type,
        "past_short_topics": past_topics,
        "current_phase": "script_writing",
        "messages": [AIMessage(content=f"Selected short topic: {chosen.topic} | Hook: {chosen.hook_angle}")],
    }
