"""Topic selection node - picks a history topic avoiding past videos."""

import asyncio
import base64
import json
import logging
import os
import random
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.core.config import settings
from prolific.services.llm import get_llm_service
from prolific.youtube.services.channel_history import get_channel_history_service
from prolific.youtube.state import YouTubePipelineState

logger = logging.getLogger(__name__)


async def _get_past_youtube_titles() -> list[str]:
    """Fetch past video titles from the Slumber Archives YouTube channel."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = None
        b64 = os.environ.get("YOUTUBE_CREDENTIALS_B64")
        if b64:
            creds_data = json.loads(base64.b64decode(b64))
        elif Path(settings.youtube_credentials_path).exists():
            creds_data = json.loads(Path(settings.youtube_credentials_path).read_text())

        if not creds_data:
            return []

        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )

        def _fetch():
            yt = build("youtube", "v3", credentials=creds)
            resp = yt.search().list(
                part="snippet", forMine=True, type="video",
                maxResults=50, order="date",
            ).execute()
            return [item["snippet"]["title"] for item in resp.get("items", [])]

        titles = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        logger.info(f"Fetched {len(titles)} past video titles from YouTube")
        return titles

    except Exception as e:
        logger.warning(f"YouTube past titles fetch failed: {e}")
        return []


class TopicCandidate(BaseModel):
    topic: str
    is_biography: bool
    era_tags: list[str] = Field(default_factory=list)
    region_tags: list[str] = Field(default_factory=list)
    appeal_reason: str = ""
    trending_tie_in: str = ""
    # Continuation flag: set ONLY when intentionally building on a past video
    # (legitimate "Part 2" with a distinct angle, not a rephrased duplicate).
    is_intentional_continuation: bool = False
    continues_video_id: str | None = None
    distinct_angle: str = ""
    continuation_rationale: str = ""


class TopicBrainstormResult(BaseModel):
    candidates: list[TopicCandidate]


class TopicSelectionResult(BaseModel):
    chosen_index: int
    rationale: str


async def _get_diversity_context(history_service) -> str:
    """Build a soft diversity constraint from the last 10 videos' era/region tags."""
    try:
        recent = await history_service.get_past_videos(limit=10)
        if not recent:
            return ""

        from collections import Counter
        era_counts: Counter = Counter()
        region_counts: Counter = Counter()
        for v in recent:
            for tag in v.era_tags:
                era_counts[tag.lower()] += 1
            for tag in v.region_tags:
                region_counts[tag.lower()] += 1

        saturated_eras = [era for era, count in era_counts.items() if count >= 3]
        saturated_regions = [region for region, count in region_counts.items() if count >= 2]

        if not saturated_eras and not saturated_regions:
            return ""

        lines = ["DIVERSITY CONSTRAINT (soft — deprioritize these, don't ban them):"]
        if saturated_eras:
            lines.append(f"- Over-represented eras in last 10 videos: {', '.join(saturated_eras)}")
            lines.append("  -> Avoid these eras unless the topic is truly exceptional.")
        if saturated_regions:
            lines.append(f"- Over-represented regions in last 10 videos: {', '.join(saturated_regions)}")
            lines.append("  -> Strongly prefer different civilizations/regions this time.")
        lines.append("These are soft constraints — if an over-represented topic is clearly the best choice, pick it. But actively look for fresh eras and regions first.")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Diversity context failed (non-fatal): {e}")
        return ""


async def _get_performance_context() -> str:
    """Pull channel analytics to identify what topics/eras/regions perform best."""
    try:
        from prolific.youtube.services.youtube_analytics import get_youtube_analytics_service
        analytics = get_youtube_analytics_service()
        insights = await analytics.get_channel_insights()
        if insights.summary and insights.total_videos_analyzed > 0:
            logger.info(f"Analytics: {insights.total_videos_analyzed} videos analyzed for performance context")
            return insights.summary
        return ""
    except Exception as e:
        logger.warning(f"Analytics fetch failed (non-fatal): {e}")
        return ""


async def _get_trending_context() -> str:
    """Search for trending news and extract historically relevant themes."""
    try:
        from prolific.services.web_search import get_web_search_service
        search_service = get_web_search_service()

        results = await search_service.search(
            query="major world news today trending stories",
            max_results=8,
            search_depth="basic",
        )

        if not results:
            return ""

        headlines = [f"- {r.title}: {r.snippet[:150]}" for r in results[:8]]
        trending_summary = "\n".join(headlines)

        logger.info(f"Fetched {len(headlines)} trending headlines for topic inspiration")
        return trending_summary

    except Exception as e:
        logger.warning(f"Trending news fetch failed (non-fatal): {e}")
        return ""


def _format_past_topics_for_prompt(past: list, fallback_titles: list[str]) -> str:
    """Format past topics with video IDs for the brainstorm prompt.

    The IDs are required so the LLM can fill `continues_video_id` when proposing
    an intentional continuation. Falls back to plain titles for any titles
    sourced from YouTube search that aren't in our DB.
    """
    lines: list[str] = []
    seen_topics: set[str] = set()
    for record in past:
        pub = record.published_at.strftime("%Y-%m-%d") if record.published_at else "?"
        line = f"- [{record.video_id}] {record.title} (published {pub})"
        lines.append(line)
        seen_topics.add(record.topic.lower().strip())
    for title in fallback_titles:
        if title.lower().strip() in seen_topics:
            continue
        lines.append(f"- {title}")
    return "\n".join(lines) if lines else "(none yet)"


async def topic_selection_node(state: YouTubePipelineState) -> dict:
    """Select an interesting history topic for the video.

    Topic selection runs through a semantic dedup gate after brainstorming —
    rejected candidates trigger one retry round with rejection feedback. Only
    candidates flagged as `is_intentional_continuation=True` (with valid parent
    video_id, ≥30-day cooldown, distinct angle) are allowed to bypass the gate.
    """
    from prolific.services.topic_dedup import (
        check_dedup,
        embed_candidates_batch,
        hydrate_embeddings,
        normalize_title,
        validate_continuation,
        build_rejection_feedback,
        _composite_text,
    )

    logger.info("=== TOPIC SELECTION ===")

    llm_service = get_llm_service()
    history_service = get_channel_history_service()
    await history_service.initialize()

    # Pull past topics WITH cached embeddings for the dedup gate.
    past_records = await history_service.get_past_topics_with_embeddings(
        limit=settings.topic_dedup_max_past_topics,
    )

    # Hydrate any records missing embeddings (cheap one-time per record).
    if settings.topic_dedup_enabled and past_records:
        async def _persist(vid_id, vec, model_v):
            await history_service.update_embedding(vid_id, vec, model_v)

        past_records = await hydrate_embeddings(
            records=past_records,
            composite_text_for_record=lambda r: _composite_text(r.topic, r.title),
            persist_callback=_persist,
        )

    yt_topics = await _get_past_youtube_titles()
    past_topics_str = _format_past_topics_for_prompt(past_records, yt_topics)
    past_topics_simple = [r.topic for r in past_records] + yt_topics

    # Normalized exact-match prefilter set (Phase A guard)
    normalized_past: set[str] = {normalize_title(r.topic) for r in past_records}
    normalized_past.update(normalize_title(t) for t in yt_topics)
    normalized_past.discard("")

    total_videos = await history_service.get_total_count()
    bio_count = await history_service.get_biography_count()
    bio_ratio = bio_count / max(total_videos, 1)
    target_ratio = settings.youtube_biography_ratio

    if bio_ratio < target_ratio:
        content_type_instruction = (
            "This video MUST be a BIOGRAPHY / character deep dive. "
            "The channel needs more biography content. Focus on a specific historical figure."
        )
    else:
        use_biography = random.random() < target_ratio
        if use_biography:
            content_type_instruction = (
                "This video should be a BIOGRAPHY / character deep dive about a specific historical figure."
            )
        else:
            content_type_instruction = (
                "This video should be a BROAD TOPIC exploration (civilization, era, event, cultural movement) "
                "rather than a single person's biography."
            )

    trending_context = await _get_trending_context()
    performance_context = await _get_performance_context()
    diversity_context = await _get_diversity_context(history_service)

    from prolific.youtube.prompts import TOPIC_BRAINSTORM_SYSTEM, TOPIC_SELECT_SYSTEM

    perf_block = performance_context if performance_context else "(no performance data yet - channel is new)"
    if diversity_context:
        perf_block = perf_block + "\n\n" + diversity_context

    async def _brainstorm(extra_feedback: str = "") -> list[TopicCandidate]:
        prompt_past = past_topics_str
        if extra_feedback:
            prompt_past = past_topics_str + "\n\nREJECTED ON LAST ATTEMPT:\n" + extra_feedback

        brainstorm_prompt = TOPIC_BRAINSTORM_SYSTEM.format(
            num_candidates=10,
            content_type_instruction=content_type_instruction,
            past_topics=prompt_past,
            trending_context=trending_context if trending_context else "(no trending data available)",
            performance_context=perf_block,
        )

        result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=brainstorm_prompt),
                HumanMessage(content="Generate topic candidates now."),
            ],
            output_schema=TopicBrainstormResult,
            tier="research",
            temperature=0.9,
        )
        return result.candidates

    candidates = await _brainstorm()
    logger.info(f"Brainstormed {len(candidates)} topic candidates")

    if not candidates:
        return {
            "errors": ["No topic candidates generated"],
            "current_phase": "failed",
        }

    # ---- DEDUP GATE ----
    accepted: list[TopicCandidate] = []
    rejection_log: list[tuple[str, object]] = []  # for retry feedback

    if settings.topic_dedup_enabled:
        # Normalized exact-match prefilter
        prefilter_keep: list[TopicCandidate] = []
        for c in candidates:
            if normalize_title(c.topic) in normalized_past:
                logger.info("DEDUP PREFILTER REJECTED '%s' (exact normalized match)", c.topic[:80])
                rejection_log.append((c.topic, type("Stub", (), {"most_similar_topic": c.topic, "similarity": 1.0, "top_matches": []})()))
            else:
                prefilter_keep.append(c)

        if prefilter_keep:
            cand_inputs = [(c.topic, c.appeal_reason) for c in prefilter_keep]
            cand_embeddings = await embed_candidates_batch(cand_inputs)

            for c, vec in zip(prefilter_keep, cand_embeddings):
                result = check_dedup(
                    candidate_topic=c.topic,
                    candidate_supporting_text=c.appeal_reason,
                    candidate_embedding=vec,
                    past=past_records,
                )
                if not result.is_dupe:
                    accepted.append(c)
                    continue

                # Dupe — but allow if intentional continuation flagged AND validated
                if c.is_intentional_continuation:
                    is_valid, reason = validate_continuation(
                        continues_video_id=c.continues_video_id,
                        distinct_angle=c.distinct_angle,
                        dedup_result=result,
                        cooldown_days=settings.topic_dedup_continuation_cooldown_days,
                    )
                    if is_valid:
                        logger.info("CONTINUATION ACCEPTED '%s' (parent=%s)", c.topic[:80], c.continues_video_id)
                        accepted.append(c)
                        continue
                    logger.info("CONTINUATION REJECTED '%s': %s", c.topic[:80], reason)

                rejection_log.append((c.topic, result))

        # Retry once if everything got rejected
        if not accepted and rejection_log:
            feedback_lines = build_rejection_feedback(
                [(t, r) for t, r in rejection_log if hasattr(r, "most_similar_topic")]
            )
            logger.info("DEDUP retry: all %d candidates rejected, re-brainstorming with feedback", len(rejection_log))

            retry_candidates = await _brainstorm(extra_feedback="\n".join(feedback_lines))
            if retry_candidates:
                cand_inputs = [(c.topic, c.appeal_reason) for c in retry_candidates]
                cand_embeddings = await embed_candidates_batch(cand_inputs)
                for c, vec in zip(retry_candidates, cand_embeddings):
                    if normalize_title(c.topic) in normalized_past:
                        continue
                    result = check_dedup(c.topic, c.appeal_reason, vec, past_records)
                    if not result.is_dupe:
                        accepted.append(c)
                    elif c.is_intentional_continuation:
                        is_valid, _ = validate_continuation(
                            c.continues_video_id, c.distinct_angle, result,
                            settings.topic_dedup_continuation_cooldown_days,
                        )
                        if is_valid:
                            accepted.append(c)

        # Hard fallback — never let pipeline stall. Pick lowest-similarity from original.
        if not accepted:
            logger.warning("DEDUP fallback: retry also empty, picking lowest-similarity original candidate")
            scored = []
            for c, r in rejection_log:
                sim = getattr(r, "similarity", 1.0)
                scored.append((sim, c))
            scored.sort(key=lambda x: x[0])
            if scored:
                # Find the candidate object
                fallback_topic = scored[0][1]
                for c in candidates:
                    if c.topic == fallback_topic:
                        accepted = [c]
                        break
            if not accepted:
                accepted = candidates[:1]
    else:
        accepted = candidates

    if not accepted:
        return {
            "errors": ["All candidates rejected and fallback failed"],
            "current_phase": "failed",
        }

    # ---- SELECTION over accepted candidates ----
    candidates_str = "\n".join(
        f"[{i}] {c.topic} (biography={c.is_biography}) - {c.appeal_reason}"
        + (f" [TRENDING: {c.trending_tie_in}]" if c.trending_tie_in else "")
        + (f" [PART 2 of {c.continues_video_id}: {c.distinct_angle}]" if c.is_intentional_continuation else "")
        for i, c in enumerate(accepted)
    )

    selection_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=TOPIC_SELECT_SYSTEM),
            HumanMessage(content=f"Candidates:\n{candidates_str}\n\nSelect the best one."),
        ],
        output_schema=TopicSelectionResult,
        tier="research",
        temperature=0.3,
    )

    chosen_idx = max(0, min(selection_result.chosen_index, len(accepted) - 1))
    chosen = accepted[chosen_idx]

    logger.info(f"Selected topic: {chosen.topic}")
    logger.info(f"Is biography: {chosen.is_biography}")
    logger.info(f"Rationale: {selection_result.rationale}")
    if chosen.trending_tie_in:
        logger.info(f"Trending tie-in: {chosen.trending_tie_in}")
    if chosen.is_intentional_continuation:
        logger.info(f"Continuation: parent={chosen.continues_video_id} angle={chosen.distinct_angle[:80]}")

    rationale = (
        f"Topic: {chosen.topic}\n"
        f"Is biography: {chosen.is_biography}\n"
        f"LLM rationale: {selection_result.rationale}\n"
        f"Performance context used: {bool(performance_context)}\n"
        f"Diversity constraint used: {bool(diversity_context)}\n"
        f"Dedup gate: {settings.topic_dedup_enabled}, accepted={len(accepted)}/{len(candidates)}\n"
        f"Continuation: {chosen.is_intentional_continuation}"
        + (f" (parent={chosen.continues_video_id}, angle={chosen.distinct_angle})" if chosen.is_intentional_continuation else "")
        + f"\nCandidates considered: {[c.topic for c in candidates]}"
    )
    logger.info(f"Selection rationale saved to DB: {selection_result.rationale}")

    return {
        "topic": chosen.topic,
        "is_biography": chosen.is_biography,
        "era_tags": chosen.era_tags,
        "region_tags": chosen.region_tags,
        "selection_rationale": rationale,
        "past_video_topics": past_topics_simple[:50],
        "is_intentional_continuation": chosen.is_intentional_continuation,
        "continues_video_id": chosen.continues_video_id,
        "current_phase": "script_planning",
        "messages": [AIMessage(content=f"Selected topic: {chosen.topic}")],
    }
