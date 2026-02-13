"""LLM-powered topic selection from discovered candidates."""

import logging

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.autonomous.content_analyzer import ExistingPostSummary
from prolific.autonomous.topic_discovery import TopicCandidate
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class SelectedTopic(BaseModel):
    topic: str
    subtopics: list[str] = Field(min_length=3, max_length=5)
    focus_areas: list[str] = Field(min_length=2, max_length=3)
    style_tone: str = "journalistic"
    rationale: str
    builds_on: str | None = None


class TopicSelectionResult(BaseModel):
    selected: SelectedTopic | None = None
    skip_reason: str | None = None


SELECTOR_PROMPT = """You are an editorial director for a technical blog focused on AI, software engineering, and system architecture.

Given a list of trending topic candidates and existing blog posts, select the SINGLE best topic for today's new blog post.

EXISTING BLOG POSTS (avoid duplicates):
{existing_posts}

TOPIC CANDIDATES:
{candidates}

SELECTION CRITERIA (in order of importance):
1. NOT a duplicate of existing posts (similar title/topic = skip it)
2. Trending and timely - prioritize topics with recent developments
3. Has enough substance and depth for a 5000-word technical article
4. Relevant to practitioners in AI, software engineering, and architecture
5. CAN be a follow-up or deeper dive on an existing post (set builds_on to the existing slug)

Generate 3-5 specific subtopics and 2-3 focus areas for the chosen topic.
The style_tone should always be "journalistic".

If ALL candidates are duplicates of existing posts, set selected to null and provide a skip_reason."""


def _format_existing_posts(posts: list[ExistingPostSummary]) -> str:
    if not posts:
        return "No existing posts yet."
    lines = []
    for p in posts:
        topics_str = ", ".join(p.topics[:5]) if p.topics else "N/A"
        lines.append(f"- [{p.slug}] \"{p.title}\" ({p.date}) - Topics: {topics_str}")
    return "\n".join(lines)


def _format_candidates(candidates: list[TopicCandidate]) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"{i}. [{c.category}] {c.title} (freshness: {c.freshness_score:.1f})\n"
            f"   {c.description}"
        )
    return "\n".join(lines)


async def select_topic(
    candidates: list[TopicCandidate],
    existing_posts: list[ExistingPostSummary],
) -> SelectedTopic | None:
    logger.info(
        f"Selecting from {len(candidates)} candidates "
        f"against {len(existing_posts)} existing posts"
    )

    llm_service = get_llm_service()
    result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content="You are an editorial director for a technical blog."),
            HumanMessage(content=SELECTOR_PROMPT.format(
                existing_posts=_format_existing_posts(existing_posts),
                candidates=_format_candidates(candidates),
            )),
        ],
        output_schema=TopicSelectionResult,
        tier="research",
        temperature=0.3,
    )

    if result.selected is None:
        logger.info(f"No topic selected: {result.skip_reason}")
        return None

    logger.info(f"Selected topic: {result.selected.topic}")
    logger.info(f"Rationale: {result.selected.rationale}")
    if result.selected.builds_on:
        logger.info(f"Builds on existing post: {result.selected.builds_on}")

    return result.selected
