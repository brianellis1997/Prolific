"""Topic selection node - finds trending content with niche awareness and content mode selection."""

import logging
from pathlib import Path

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
    content_mode: str = "news_commentary"
    hook_angle: str = ""
    virality_reason: str = ""
    visual_keywords: list[str] = Field(default_factory=list)
    trending_tie_in: str = ""
    clip_search_queries: list[str] = Field(default_factory=list)
    scene_ideas: list[str] = Field(default_factory=list)
    # Continuation flag: set ONLY when intentionally building on a past short
    # (legitimate "Part 2" with a distinct angle, not a rephrased duplicate).
    is_intentional_continuation: bool = False
    continues_video_id: str | None = None
    distinct_angle: str = ""
    continuation_rationale: str = ""


class ShortTopicBrainstorm(BaseModel):
    candidates: list[ShortTopicCandidate]


class ShortTopicSelection(BaseModel):
    chosen_index: int
    rationale: str


async def _get_trending_context(niche: str) -> tuple[str, list[str]]:
    try:
        from prolific.services.web_search import get_web_search_service
        from prolific.shorts.prompts import NICHE_SEARCH_QUERIES
        search_service = get_web_search_service()

        import random
        all_queries = NICHE_SEARCH_QUERIES.get(niche, NICHE_SEARCH_QUERIES["general"])
        queries = random.sample(all_queries, min(5, len(all_queries)))
        logger.info(f"Search queries this run: {queries}")

        all_headlines = []
        all_urls = []
        for query in queries:
            results = await search_service.search(
                query=query,
                max_results=5,
                search_depth="basic",
            )
            for r in results or []:
                all_headlines.append(f"- {r.title}: {r.snippet[:150]}")
                if hasattr(r, "url") and r.url:
                    all_urls.append(r.url)

        seen = set()
        unique = []
        for h in all_headlines:
            key = h[:60]
            if key not in seen:
                seen.add(key)
                unique.append(h)

        logger.info(f"Fetched {len(unique)} trending headlines for niche '{niche}'")
        return "\n".join(unique[:15]), list(dict.fromkeys(all_urls))[:10]

    except Exception as e:
        logger.warning(f"Trending news fetch failed (non-fatal): {e}")
        return "", []


async def _get_past_video_titles() -> list[str]:
    """Fetch recent video titles directly from YouTube — the source of truth."""
    try:
        import asyncio
        import json
        import base64
        import os
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = None
        b64 = os.environ.get("SHORTS_CREDENTIALS_B64")
        if b64:
            creds_data = json.loads(base64.b64decode(b64))
        elif Path(settings.shorts_credentials_path).exists():
            creds_data = json.loads(Path(settings.shorts_credentials_path).read_text())

        if not creds_data:
            logger.warning("No shorts credentials for past video lookup")
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
        logger.warning(f"YouTube past titles fetch failed (non-fatal): {e}")
        return []


async def _get_shorts_performance_context() -> str:
    """Pull YouTube analytics for the shorts channel to identify top-performing topics."""
    try:
        from prolific.youtube.services.youtube_analytics import YouTubeAnalyticsService
        analytics = YouTubeAnalyticsService(credentials_path=settings.shorts_credentials_path)
        insights = await analytics.get_channel_insights(
            db_path=settings.shorts_history_db_path,
            table="shorts",
        )
        if insights.summary and insights.total_videos_analyzed > 2:
            logger.info(f"Shorts analytics: {insights.total_videos_analyzed} videos analyzed")
            return insights.summary
        return ""
    except Exception as e:
        logger.warning(f"Shorts analytics fetch failed (non-fatal): {e}")
        return ""


async def _verify_clips_available(candidate: ShortTopicCandidate) -> list[str]:
    """Quick check if clips are findable for a candidate. Returns verified URLs."""
    if candidate.content_mode == "news_commentary":
        return []
    if not candidate.clip_search_queries:
        return []

    try:
        from prolific.shorts.services.clip_discovery import discover_clips
        clips = await discover_clips(
            topic=candidate.clip_search_queries[0],
            niche="general",
            max_clips=3,
        )
        return [c["url"] for c in clips if c.get("url")]
    except Exception as e:
        logger.warning(f"Clip verification failed: {e}")
        return []


def _is_ai_video_run() -> bool:
    """Check if this run should use AI video generation (Kling) based on config, time, and day.

    AI video runs on specific hours AND specific days of the week.
    Default: Mon/Wed/Fri at hour 16 (4 PM ET) ONLY.

    Reads env vars directly to avoid stale @lru_cache values.
    """
    import os
    if not settings.kling_enabled or not settings.fal_api_key:
        return False
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
        current_hour = now.hour
        current_day = now.weekday()  # 0=Monday, 6=Sunday

        hours_str = os.environ.get("KLING_CRON_HOURS", settings.kling_cron_hours)
        days_str = os.environ.get("KLING_CRON_DAYS", getattr(settings, "kling_cron_days", "0,2,4"))

        allowed_hours = [int(h.strip()) for h in hours_str.split(",") if h.strip()]
        allowed_days = [int(d.strip()) for d in days_str.split(",") if d.strip()]

        result = current_hour in allowed_hours and current_day in allowed_days
        logger.info(
            f"AI video check: hour={current_hour} day={current_day} "
            f"allowed_hours={allowed_hours} allowed_days={allowed_days} -> {result}"
        )
        return result
    except Exception:
        return False


def _format_past_topics_for_prompt(past_records: list, fallback_titles: list[str]) -> str:
    """Format past shorts with video IDs for the brainstorm prompt.

    IDs are required so the LLM can fill `continues_video_id` for intentional
    continuations. Falls back to plain titles for YouTube-search results not in
    our DB.
    """
    lines: list[str] = []
    seen_topics: set[str] = set()
    for record in past_records:
        pub = record.published_at.strftime("%Y-%m-%d") if record.published_at else "?"
        lines.append(f"- [{record.video_id}] {record.topic} (published {pub})")
        seen_topics.add(record.topic.lower().strip())
    for title in fallback_titles:
        if title.lower().strip() in seen_topics:
            continue
        lines.append(f"- {title}")
    return "\n".join(lines) if lines else "(none yet)"


async def _run_dedup_gate(
    candidates: list[ShortTopicCandidate],
    past_records: list,
    normalized_past: set[str],
):
    """Run the prefilter + semantic gate over candidates.

    Returns (accepted_list, rejection_log) for the retry path.
    """
    from prolific.services.topic_dedup import (
        check_dedup,
        embed_candidates_batch,
        normalize_title,
        validate_continuation,
    )

    accepted: list[ShortTopicCandidate] = []
    rejection_log: list[tuple[str, object]] = []

    prefilter_keep: list[ShortTopicCandidate] = []
    for c in candidates:
        if normalize_title(c.topic) in normalized_past:
            logger.info("DEDUP PREFILTER REJECTED short '%s' (exact normalized match)", c.topic[:80])
            stub = type("Stub", (), {"most_similar_topic": c.topic, "similarity": 1.0, "top_matches": []})()
            rejection_log.append((c.topic, stub))
        else:
            prefilter_keep.append(c)

    if prefilter_keep and past_records:
        cand_inputs = [(c.topic, c.hook_angle) for c in prefilter_keep]
        cand_embeddings = await embed_candidates_batch(cand_inputs)

        for c, vec in zip(prefilter_keep, cand_embeddings):
            result = check_dedup(c.topic, c.hook_angle, vec, past_records)
            if not result.is_dupe:
                accepted.append(c)
                continue

            if c.is_intentional_continuation:
                is_valid, reason = validate_continuation(
                    continues_video_id=c.continues_video_id,
                    distinct_angle=c.distinct_angle,
                    dedup_result=result,
                    cooldown_days=settings.shorts_continuation_cooldown_days,
                )
                if is_valid:
                    logger.info("CONTINUATION ACCEPTED short '%s' (parent=%s)", c.topic[:80], c.continues_video_id)
                    accepted.append(c)
                    continue
                logger.info("CONTINUATION REJECTED short '%s': %s", c.topic[:80], reason)

            rejection_log.append((c.topic, result))
    else:
        accepted = prefilter_keep

    return accepted, rejection_log


async def topic_selection_node(state: ShortsPipelineState) -> dict:
    """Select a topic with niche awareness and content mode determination.

    Topic selection runs through a semantic dedup gate after brainstorming —
    rejected candidates trigger one retry round with rejection feedback. Only
    candidates flagged as `is_intentional_continuation=True` (with valid parent
    video_id, ≥14-day cooldown for shorts, distinct angle) are allowed to
    bypass the gate.
    """
    from prolific.services.topic_dedup import (
        build_rejection_feedback,
        check_entity_overlap,
        entity_extraction,
        hydrate_embeddings,
        normalize_title,
        _composite_text,
        _rich_composite_text,
    )

    logger.info("=== SHORTS: TOPIC SELECTION ===")

    llm_service = get_llm_service()
    history_service = get_shorts_history_service()

    niche = state.get("niche") or settings.shorts_niche or "general"
    logger.info(f"Niche: {niche}")

    if niche == "twitch":
        logger.info("Twitch niche detected — routing directly to twitch_discovery")
        return {
            "niche": niche,
            "content_mode": "twitch_clips",
            "current_phase": "twitch_discovery",
            "messages": [AIMessage(content="Twitch niche: routing to Twitch drama discovery")],
        }

    # Past topics: DB pull (with embeddings) is authoritative, YouTube search is supplementary
    past_records = await history_service.get_past_topics_with_embeddings(
        limit=settings.topic_dedup_max_past_topics,
    )
    if settings.topic_dedup_enabled and past_records:
        async def _persist(vid_id, vec, model_v):
            await history_service.update_embedding(vid_id, vec, model_v)

        async def _persist_entities(vid_id, ents):
            await history_service.update_entities(vid_id, ents)

        past_records = await hydrate_embeddings(
            records=past_records,
            composite_text_for_record=lambda r: _rich_composite_text(r.topic, r.title, r.script_excerpt),
            persist_callback=_persist,
            persist_entities_callback=_persist_entities,
        )

    yt_topics = await _get_past_video_titles()
    past_topics_str = _format_past_topics_for_prompt(past_records, yt_topics)
    past_topics = [r.topic for r in past_records] + yt_topics

    normalized_past: set[str] = {normalize_title(r.topic) for r in past_records}
    normalized_past.update(normalize_title(t) for t in yt_topics)
    normalized_past.discard("")

    trending_context, source_urls = await _get_trending_context(niche)
    performance_context = await _get_shorts_performance_context()

    ai_video_mode = _is_ai_video_run()
    if ai_video_mode:
        logger.info("AI video mode ACTIVE — using scenario-driven topic prompts")

    # Resolve which prompts to use based on niche + AI video mode
    select_prompt: str
    extra_trending = ""

    if niche == "curiosity" and ai_video_mode:
        from prolific.shorts.prompts import (
            SCENARIO_TOPIC_BRAINSTORM_SYSTEM,
            SCENARIO_TOPIC_SELECT_SYSTEM,
            NICHE_SEARCH_QUERIES,
        )
        import random as _random
        scenario_queries = NICHE_SEARCH_QUERIES.get("curiosity_scenario", [])
        if scenario_queries:
            from prolific.services.web_search import get_web_search_service
            search_service = get_web_search_service()
            sampled = _random.sample(scenario_queries, min(3, len(scenario_queries)))
            for q in sampled:
                try:
                    results = await search_service.search(query=q, max_results=3, search_depth="basic")
                    for r in results or []:
                        extra_trending += f"- {r.title}: {r.snippet[:120]}\n"
                except Exception:
                    pass
        brainstorm_template = SCENARIO_TOPIC_BRAINSTORM_SYSTEM
        select_prompt = SCENARIO_TOPIC_SELECT_SYSTEM
        prompt_branch = "scenario"
    elif niche == "curiosity":
        from prolific.shorts.prompts import (
            CURIOSITY_TOPIC_BRAINSTORM_SYSTEM,
            CURIOSITY_TOPIC_SELECT_SYSTEM,
        )
        brainstorm_template = CURIOSITY_TOPIC_BRAINSTORM_SYSTEM
        select_prompt = CURIOSITY_TOPIC_SELECT_SYSTEM
        prompt_branch = "curiosity"
    else:
        from prolific.shorts.prompts import (
            NICHE_DESCRIPTIONS,
            NICHE_TOPIC_BRAINSTORM_SYSTEM,
            TOPIC_SELECT_SYSTEM,
        )
        niche_description = NICHE_DESCRIPTIONS.get(niche, NICHE_DESCRIPTIONS["general"])
        brainstorm_template = NICHE_TOPIC_BRAINSTORM_SYSTEM
        select_prompt = TOPIC_SELECT_SYSTEM
        prompt_branch = "niche"

    combined_trending = (trending_context + "\n" + extra_trending).strip() if trending_context else extra_trending.strip()

    async def _brainstorm(extra_feedback: str = "") -> list[ShortTopicCandidate]:
        prompt_past = past_topics_str
        if extra_feedback:
            prompt_past = past_topics_str + "\n\nREJECTED ON LAST ATTEMPT:\n" + extra_feedback

        if prompt_branch == "scenario":
            prompt = brainstorm_template.format(
                num_candidates=8,
                trending_context=combined_trending if combined_trending else "(no trending data available)",
                past_topics=prompt_past,
                performance_context=performance_context if performance_context else "(no performance data yet — channel is new)",
            )
        elif prompt_branch == "curiosity":
            prompt = brainstorm_template.format(
                num_candidates=8,
                trending_context=trending_context if trending_context else "(no trending data available)",
                past_topics=prompt_past,
                performance_context=performance_context if performance_context else "(no performance data yet — channel is new)",
            )
        else:  # niche
            prompt = brainstorm_template.format(
                niche_description=niche_description,
                num_candidates=8,
                trending_context=trending_context if trending_context else "(no trending data available)",
                past_topics=prompt_past,
            )

        result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=prompt),
                HumanMessage(content="Generate topic candidates now."),
            ],
            output_schema=ShortTopicBrainstorm,
            tier="research",
            temperature=0.9,
        )
        return result.candidates

    candidates = await _brainstorm()
    logger.info(f"Brainstormed {len(candidates)} short topic candidates")

    if not candidates:
        return {
            "errors": ["No topic candidates generated"],
            "current_phase": "failed",
        }

    # ---- DEDUP GATE ----
    if settings.topic_dedup_enabled:
        accepted, rejection_log = await _run_dedup_gate(candidates, past_records, normalized_past)

        # Retry once if everything got rejected
        if not accepted and rejection_log:
            feedback_lines = build_rejection_feedback(
                [(t, r) for t, r in rejection_log if hasattr(r, "most_similar_topic")]
            )
            logger.info("DEDUP retry: all %d short candidates rejected, re-brainstorming with feedback", len(rejection_log))
            retry = await _brainstorm(extra_feedback="\n".join(feedback_lines))
            if retry:
                accepted, _ = await _run_dedup_gate(retry, past_records, normalized_past)

        # Hard fallback — never let pipeline stall
        if not accepted:
            logger.warning("DEDUP fallback: picking lowest-similarity short candidate")
            scored = []
            for c, r in rejection_log:
                sim = getattr(r, "similarity", 1.0)
                # Recover the candidate object
                for orig in candidates:
                    if orig.topic == c:
                        scored.append((sim, orig))
                        break
            scored.sort(key=lambda x: x[0])
            accepted = [scored[0][1]] if scored else candidates[:1]
    else:
        accepted = candidates

    if not accepted:
        return {
            "errors": ["All short candidates rejected and fallback failed"],
            "current_phase": "failed",
        }

    # ---- ENTITY GATE (v2) ----
    # Hard-block any candidate whose canonical entities overlap a past short's
    # entities within shorts_continuation_cooldown_days (default 14d). Catches
    # LLM-rephrased entity-rename evasion that the cosine gate misses.
    if settings.topic_dedup_enabled and settings.topic_dedup_entity_gate_enabled and past_records:
        entity_filtered: list[ShortTopicCandidate] = []
        for c in accepted:
            try:
                cand_entities = await entity_extraction(f"{c.topic} | {c.hook_angle}")
            except Exception as exc:
                logger.warning("Entity extraction failed for short '%s': %s — failing open", c.topic[:60], exc)
                entity_filtered.append(c)
                continue
            overlap = check_entity_overlap(
                candidate_entities=cand_entities,
                past=past_records,
                cooldown_days=settings.topic_dedup_entity_cooldown_days,
            )
            if overlap.is_dupe and not c.is_intentional_continuation:
                logger.info(
                    "DEDUP entity-gate REJECTED short '%s' — entities=%s, %s",
                    c.topic[:60], cand_entities, overlap.reject_reason,
                )
                continue
            entity_filtered.append(c)

        if entity_filtered:
            accepted = entity_filtered
        else:
            logger.warning("Entity gate rejected ALL short candidates — keeping cosine-accepted set to avoid stall")

    candidates_str = "\n".join(
        f"[{i}] {c.topic} ({c.topic_type}, mode={c.content_mode}) - {c.hook_angle}"
        + (f" [TRENDING: {c.trending_tie_in}]" if c.trending_tie_in else "")
        + (f" [PART 2 of {c.continues_video_id}: {c.distinct_angle}]" if c.is_intentional_continuation else "")
        for i, c in enumerate(accepted)
    )

    selection_result = await llm_service.invoke_with_structured_output(
        messages=[
            SystemMessage(content=select_prompt),
            HumanMessage(content=f"Candidates:\n{candidates_str}\n\nSelect the best one."),
        ],
        output_schema=ShortTopicSelection,
        tier="research",
        temperature=0.3,
    )

    chosen_idx = max(0, min(selection_result.chosen_index, len(accepted) - 1))
    chosen = accepted[chosen_idx]

    content_mode = chosen.content_mode
    valid_modes = {"news_commentary", "clip_reaction", "clip_compilation", "niche_drama"}
    if content_mode not in valid_modes:
        content_mode = "news_commentary"
    if niche == "curiosity":
        content_mode = "news_commentary"

    verified_urls = []
    if content_mode != "news_commentary":
        verified_urls = await _verify_clips_available(chosen)
        if not verified_urls:
            logger.info(f"No clips found for '{chosen.topic}', falling back to news_commentary")
            content_mode = "news_commentary"
        else:
            logger.info(f"Verified {len(verified_urls)} clips available for '{chosen.topic}'")

    all_urls = list(dict.fromkeys(source_urls + verified_urls))

    logger.info(f"Selected short topic: {chosen.topic}")
    logger.info(f"Type: {chosen.topic_type}")
    logger.info(f"Content mode: {content_mode}")
    logger.info(f"Hook: {chosen.hook_angle}")
    if chosen.scene_ideas:
        logger.info(f"Scene ideas: {len(chosen.scene_ideas)} scenes planned")
        for i, scene in enumerate(chosen.scene_ideas, 1):
            logger.info(f"  Scene {i}: {scene[:80]}")

    selection_rationale = (
        f"Topic: {chosen.topic}\n"
        f"Hook: {chosen.hook_angle}\n"
        f"LLM rationale: {selection_result.rationale}\n"
        f"Virality reason: {chosen.virality_reason}\n"
        f"Performance context used: {bool(performance_context)}\n"
        f"AI video mode: {ai_video_mode}\n"
        f"Candidates considered: {[c.topic for c in candidates]}"
    )
    logger.info(f"Selection rationale: {selection_result.rationale}")

    return {
        "topic": chosen.topic,
        "topic_type": chosen.topic_type,
        "content_mode": content_mode,
        "niche": niche,
        "source_urls": all_urls,
        "past_short_topics": past_topics,
        "scene_ideas": chosen.scene_ideas or [],
        "selection_rationale": selection_rationale,
        "is_intentional_continuation": chosen.is_intentional_continuation,
        "continues_video_id": chosen.continues_video_id,
        "current_phase": "script_writing",
        "messages": [AIMessage(
            content=f"Selected: {chosen.topic} | Mode: {content_mode} | Hook: {chosen.hook_angle}"
        )],
    }
