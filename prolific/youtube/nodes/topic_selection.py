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
    # click_hypothesis: required answer to "why would a scrolling viewer stop and
    # click on THIS video over the next thing in their feed?". Forces the LLM to
    # think like a creator optimizing for CTR rather than a researcher cataloging
    # interesting facts. Weighted heavily in selection.
    click_hypothesis: str = ""
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


async def _build_content_type_instruction(history_service, content_mode: str) -> str:
    """Build the brainstorm `content_type_instruction` for the given content mode.

    For BIOGRAPHY mode, computes the bio-ratio (biographies / total BIOGRAPHY-mode videos)
    and biases toward biographies-vs-broad-topic accordingly. The denominator is the
    BIOGRAPHY-mode count, NOT the total — otherwise LOST_CIVILIZATION/IMMERSIVE uploads
    deflate the ratio and over-skew Mon/Wed/Fri toward forced biographies.

    For LOST_CIVILIZATION and IMMERSIVE_DAILY_LIFE, returns the fixed mode-specific
    instruction from prompts.py.
    """
    from prolific.youtube.prompts import (
        CONTENT_INSTRUCTION_BIOGRAPHY_FIXED,
        CONTENT_INSTRUCTION_BIOGRAPHY_FORCED,
        CONTENT_INSTRUCTION_BROAD_TOPIC,
        CONTENT_INSTRUCTION_IMMERSIVE,
        CONTENT_INSTRUCTION_LOSTCIV,
    )

    if content_mode == "LOST_CIVILIZATION":
        return CONTENT_INSTRUCTION_LOSTCIV
    if content_mode == "IMMERSIVE_DAILY_LIFE":
        return CONTENT_INSTRUCTION_IMMERSIVE

    # BIOGRAPHY mode (default) — biography-vs-broad-topic biasing.
    # Denominator filters to BIOGRAPHY-mode videos so other modes don't deflate the ratio.
    bio_mode_count = await history_service.get_count_by_mode("BIOGRAPHY")
    bio_count = await history_service.get_biography_count()
    bio_ratio = bio_count / max(bio_mode_count, 1)
    target_ratio = settings.youtube_biography_ratio

    if bio_ratio < target_ratio:
        return CONTENT_INSTRUCTION_BIOGRAPHY_FORCED
    use_biography = random.random() < target_ratio
    return CONTENT_INSTRUCTION_BIOGRAPHY_FIXED if use_biography else CONTENT_INSTRUCTION_BROAD_TOPIC


async def _get_diversity_context(history_service, content_mode: str = "BIOGRAPHY") -> str:
    """Build a soft diversity constraint from the last 10 videos' era/region tags.

    Filtered by `content_mode` so a Saturday IMMERSIVE_DAILY_LIFE upload doesn't
    suppress a Monday BIOGRAPHY about the same era — each mode keeps its own
    diversity signal.
    """
    try:
        recent = await history_service.get_past_videos(limit=10, content_mode=content_mode)
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


_COMPETITOR_CACHE: dict[str, tuple[float, str]] = {}  # key: cache_key → (expires_at_ts, block_text)


def _get_yt_client():
    """Build an authenticated YT Data API client for read operations."""
    import json
    import os
    import base64
    from pathlib import Path as _Path
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    env_key = os.environ.get("YOUTUBE_CREDENTIALS_B64")
    if env_key:
        creds_data = json.loads(base64.b64decode(env_key))
    else:
        cred_path = settings.youtube_credentials_path
        if not _Path(cred_path).exists():
            return None
        creds_data = json.loads(_Path(cred_path).read_text())
    creds = Credentials(
        token=creds_data.get("token"),
        refresh_token=creds_data.get("refresh_token"),
        token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_data.get("client_id"),
        client_secret=creds_data.get("client_secret"),
    )
    return build("youtube", "v3", credentials=creds)


async def _get_hot_niche_titles() -> str:
    """YT search for trending sleep-history content (view-weighted, recent).

    Complements the fixed-channel scrape. Pulls top videos in the niche
    regardless of which channel posted them, sorted by view count, from
    the last N days. Gives the prompt LIVE signal about what's currently
    hot rather than a static reference set.

    Each YT search call is 100 quota units. With 4 default queries + 22
    pipeline runs/month, that's 4×100×22 = 8800 quota/mo, well under
    the 300K/mo free tier. Cached 6h to amortize bursts.
    """
    import time
    queries = [q.strip() for q in settings.youtube_niche_search_queries.split(",") if q.strip()]
    if not queries:
        return ""
    cache_key = "hot::" + ",".join(sorted(queries)) + f"::{settings.youtube_niche_search_days}d"
    now = time.time()
    cached = _COMPETITOR_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]

    try:
        yt = _get_yt_client()
        if yt is None:
            return ""
        from datetime import datetime, timezone, timedelta
        published_after = (datetime.now(timezone.utc) - timedelta(days=settings.youtube_niche_search_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        all_rows: list[tuple[int, str, str]] = []  # (views, title, channel)
        for q in queries:
            try:
                # Filter to long videos (>20 min) to skip shorts, sorted by view count, recent
                sr = yt.search().list(
                    part="snippet", q=q, type="video", order="viewCount",
                    publishedAfter=published_after, videoDuration="long",
                    maxResults=settings.youtube_niche_search_per_query,
                ).execute()
                vids = sr.get("items", [])
                if not vids:
                    continue
                vid_ids = [v["id"]["videoId"] for v in vids if v.get("id", {}).get("videoId")]
                if not vid_ids:
                    continue
                # Fetch view counts (search response doesn't include them reliably)
                stats = yt.videos().list(part="statistics,snippet", id=",".join(vid_ids)).execute()
                for it in stats.get("items", []):
                    title = it["snippet"]["title"]
                    channel = it["snippet"]["channelTitle"]
                    views = int(it["statistics"].get("viewCount", 0))
                    all_rows.append((views, title, channel))
            except Exception as inner:
                logger.warning(f"Niche search '{q}' failed: {inner}")
                continue
        if not all_rows:
            return ""
        # Dedup by title, keep highest-view variant; sort by views desc
        best_by_title: dict[str, tuple[int, str, str]] = {}
        for views, title, ch in all_rows:
            cur = best_by_title.get(title)
            if not cur or cur[0] < views:
                best_by_title[title] = (views, title, ch)
        rows = sorted(best_by_title.values(), key=lambda r: -r[0])[:15]
        lines = [f'    [{views:>6,} views, {ch}] "{title}"' for views, title, ch in rows]
        block = (
            f"HOT NICHE TITLES (top sleep/history videos posted in the last "
            f"{settings.youtube_niche_search_days} days, sorted by views — "
            "what's resonating in the niche RIGHT NOW):\n" + "\n".join(lines)
        )
        _COMPETITOR_CACHE[cache_key] = (now + 6 * 3600, block)  # 6h TTL
        logger.info(f"Hot niche titles: {len(rows)} videos pulled across {len(queries)} queries")
        return block
    except Exception as exc:
        logger.warning(f"Hot niche search failed (non-fatal): {exc}")
        return ""


async def _fetch_fixed_competitor_block() -> str:
    """Latest top uploads from the configured competitor channels."""
    import time
    channel_ids = [c.strip() for c in settings.youtube_competitor_channel_ids.split(",") if c.strip()]
    if not channel_ids:
        return ""
    cache_key = "fixed::" + ",".join(sorted(channel_ids))
    now = time.time()
    cached = _COMPETITOR_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1]
    try:
        yt = _get_yt_client()
        if yt is None:
            return ""
        per_channel = settings.youtube_competitor_videos_per_channel
        sections: list[str] = []
        for cid in channel_ids:
            try:
                ch_resp = yt.channels().list(part="snippet,statistics", id=cid).execute()
                if not ch_resp.get("items"):
                    continue
                ch = ch_resp["items"][0]
                title = ch["snippet"]["title"]
                subs = int(ch["statistics"].get("subscriberCount", 0))
                uploads_pl = "UU" + cid[2:]
                pl = yt.playlistItems().list(
                    part="snippet,contentDetails", playlistId=uploads_pl, maxResults=per_channel,
                ).execute()
                vids = pl.get("items", [])
                if not vids:
                    continue
                vid_ids = [v["contentDetails"]["videoId"] for v in vids]
                stats_resp = yt.videos().list(part="statistics", id=",".join(vid_ids)).execute()
                stats_by_id = {it["id"]: it["statistics"] for it in stats_resp.get("items", [])}
                rows: list[tuple[int, str]] = []
                for v in vids:
                    vid = v["contentDetails"]["videoId"]
                    t = v["snippet"]["title"]
                    views = int(stats_by_id.get(vid, {}).get("viewCount", 0))
                    rows.append((views, t))
                rows.sort(key=lambda r: -r[0])
                lines = [f'    [{views:>6,} views] "{t}"' for views, t in rows[:per_channel]]
                sections.append(f"  {title} ({subs:,} subs):\n" + "\n".join(lines))
            except Exception as inner:
                logger.warning(f"Competitor fetch failed for {cid}: {inner}")
                continue
        if not sections:
            return ""
        block = (
            "FIXED COMPETITOR CHANNELS (recent top uploads from the same sleep-history peers):\n"
            + "\n\n".join(sections)
        )
        _COMPETITOR_CACHE[cache_key] = (now + 3600, block)  # 1h TTL
        logger.info(f"Fixed competitor block: {len(sections)} channels")
        return block
    except Exception as exc:
        logger.warning(f"Fixed competitor fetch failed (non-fatal): {exc}")
        return ""


async def _get_competitor_inspiration() -> str:
    """Compose the full click-inspiration block — fixed channels + hot-niche search.

    Both feed into prompts as INSPIRATION, never as templates. AVOID-STEMS +
    the prompt's anti-copy guidance prevent verbatim reuse.
    """
    fixed_block = await _fetch_fixed_competitor_block()
    hot_block = await _get_hot_niche_titles()
    if not fixed_block and not hot_block:
        return ""
    parts = [
        "LIVE COMPETITOR INSPIRATION — what's actually winning in the niche RIGHT NOW.",
        "Use as a snapshot of the language, framings, and topic-shapes that resonate.",
        "**Never copy verbatim** — the AVOID-STEMS rule still applies. Steal energy, not words.",
    ]
    if hot_block:
        parts.append("")
        parts.append(hot_block)
    if fixed_block:
        parts.append("")
        parts.append(fixed_block)
    combined = "\n".join(parts)
    return combined


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
        check_entity_overlap,
        embed_candidates_batch,
        entity_extraction,
        hydrate_embeddings,
        normalize_title,
        validate_continuation,
        build_rejection_feedback,
        _composite_text,
        _rich_composite_text,
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
    # v2: rich composite (topic+title+description) and entity extraction.
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

    yt_topics = await _get_past_youtube_titles()
    past_topics_str = _format_past_topics_for_prompt(past_records, yt_topics)
    past_topics_simple = [r.topic for r in past_records] + yt_topics

    # Normalized exact-match prefilter set (Phase A guard)
    normalized_past: set[str] = {normalize_title(r.topic) for r in past_records}
    normalized_past.update(normalize_title(t) for t in yt_topics)
    normalized_past.discard("")

    # ---- CONTENT MODE ROUTING ----
    # The scheduler injects content_mode per cron job (Mon/Wed/Fri=BIOGRAPHY,
    # Thu=LOST_CIVILIZATION, Sat=IMMERSIVE_DAILY_LIFE). API-triggered runs default
    # to BIOGRAPHY for back-compat. We do NOT read datetime.now().weekday() —
    # the scheduling concern stays in the scheduler.
    content_mode = state.get("content_mode") or "BIOGRAPHY"
    logger.info(f"Content mode: {content_mode}")

    content_type_instruction = await _build_content_type_instruction(history_service, content_mode)

    trending_context = await _get_trending_context()
    performance_context = await _get_performance_context()
    diversity_context = await _get_diversity_context(history_service, content_mode=content_mode)
    competitor_block = await _get_competitor_inspiration()

    # Dynamic AVOID-STEMS list: pull the first-3-word stems of recent video titles so
    # the LLM is told explicitly which opening phrases it has overused. This catches
    # patterns the mode-specific prompts can't enumerate ahead of time — e.g.
    # "What They Found Beneath ___" emerged from the LLM, not the prompt, and once
    # it shipped twice it should be in the AVOID list automatically.
    avoid_stems_block = ""
    try:
        recent_titles = await history_service.get_recent_titles(limit=14)
        if recent_titles:
            from collections import Counter
            stems = Counter()
            for title, _topic in recent_titles:
                stem = normalize_title(title)
                words = stem.split()[:3]
                if len(words) >= 3:
                    stems[" ".join(words)] += 1
            # Any 3-word stem that's appeared on the channel at all goes in AVOID
            avoid_lines = [f"  - {p!r}" for p, _c in stems.most_common(20)]
            if avoid_lines:
                avoid_stems_block = (
                    "\n\nAVOID-STEMS (banned title openings on this channel — your title "
                    "MUST NOT start with any of these first-3-word phrases):\n"
                    + "\n".join(avoid_lines)
                )
    except Exception as exc:
        logger.warning(f"Could not load AVOID-STEMS (non-fatal): {exc}")

    from prolific.youtube.prompts import TOPIC_BRAINSTORM_SYSTEM, TOPIC_SELECT_SYSTEM

    perf_block = performance_context if performance_context else "(no performance data yet - channel is new)"
    if diversity_context:
        perf_block = perf_block + "\n\n" + diversity_context

    async def _brainstorm(extra_feedback: str = "") -> list[TopicCandidate]:
        prompt_past = past_topics_str
        if extra_feedback:
            prompt_past = past_topics_str + "\n\nREJECTED ON LAST ATTEMPT:\n" + extra_feedback

        # Compose: mode instruction + AVOID-STEMS + competitor inspiration block.
        # Competitor block is the "what's working in this niche right now" signal —
        # acts as creative oxygen so the brainstorm isn't stuck in our channel's
        # own history. The AVOID-STEMS rule still applies to prevent copying.
        full_instruction = content_type_instruction + avoid_stems_block
        if competitor_block:
            full_instruction += "\n\n" + competitor_block

        brainstorm_prompt = TOPIC_BRAINSTORM_SYSTEM.format(
            num_candidates=10,
            content_type_instruction=full_instruction,
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

                # Validate the continuation flag up-front if set, even when cosine
                # would accept the candidate. The downstream metadata node forces
                # "(Part 2)" into the title whenever this flag is true; an LLM
                # that flags a thematic-followup as a sequel (e.g. pirate-cooks
                # tagged as Part 2 of a Blackbeard biography) must be demoted
                # here or viewers see a misleading "(Part 2)" with no Part 1.
                if c.is_intentional_continuation:
                    is_valid, reason = validate_continuation(
                        continues_video_id=c.continues_video_id,
                        distinct_angle=c.distinct_angle,
                        dedup_result=result,
                        cooldown_days=settings.topic_dedup_continuation_cooldown_days,
                        current_content_mode=content_mode,
                        past_records=past_records,
                    )
                    if not is_valid:
                        logger.info("CONTINUATION FLAG DEMOTED '%s': %s", c.topic[:80], reason)
                        c.is_intentional_continuation = False

                if not result.is_dupe:
                    accepted.append(c)
                    continue

                if c.is_intentional_continuation:
                    logger.info("CONTINUATION ACCEPTED '%s' (parent=%s)", c.topic[:80], c.continues_video_id)
                    accepted.append(c)
                    continue

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

                    if c.is_intentional_continuation:
                        is_valid, reason = validate_continuation(
                            c.continues_video_id, c.distinct_angle, result,
                            settings.topic_dedup_continuation_cooldown_days,
                            current_content_mode=content_mode,
                            past_records=past_records,
                        )
                        if not is_valid:
                            logger.info("CONTINUATION FLAG DEMOTED '%s': %s", c.topic[:80], reason)
                            c.is_intentional_continuation = False

                    if not result.is_dupe:
                        accepted.append(c)
                    elif c.is_intentional_continuation:
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

    # ---- ENTITY GATE (v2) ----
    # Hard-block any candidate whose canonical entities overlap a past video's
    # entities within cooldown. Catches LLM-rephrased entity-rename evasion that
    # the cosine gate misses (e.g. "bird with deadly harpoon" vs past "woodpecker
    # tongue" — same entity per LLM, but cosine ~0.59).
    if settings.topic_dedup_enabled and settings.topic_dedup_entity_gate_enabled and past_records:
        entity_filtered: list[TopicCandidate] = []
        for c in accepted:
            try:
                cand_entities = await entity_extraction(f"{c.topic} | {c.appeal_reason}")
            except Exception as exc:
                logger.warning("Entity extraction failed for '%s': %s — failing open", c.topic[:60], exc)
                entity_filtered.append(c)
                continue
            overlap = check_entity_overlap(
                candidate_entities=cand_entities,
                past=past_records,
                cooldown_days=settings.topic_dedup_entity_cooldown_days,
            )
            if overlap.is_dupe and not c.is_intentional_continuation:
                logger.info(
                    "DEDUP entity-gate REJECTED '%s' — entities=%s, %s",
                    c.topic[:60], cand_entities, overlap.reject_reason,
                )
                continue
            entity_filtered.append(c)

        if entity_filtered:
            accepted = entity_filtered
        else:
            logger.warning("Entity gate rejected ALL candidates — keeping cosine-accepted set to avoid stall")

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
        "content_mode": content_mode,
        "competitor_inspiration": competitor_block or "",
        "current_phase": "script_planning",
        "messages": [AIMessage(content=f"Selected topic: {chosen.topic} [mode={content_mode}]")],
    }
