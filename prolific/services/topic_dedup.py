"""Shared topic-deduplication module for YouTube long-form and Shorts pipelines.

Provides a semantic-similarity gate over past topic embeddings, plus validation
for the `is_intentional_continuation` flag (deliberate sequels). Reuses the
existing `EmbeddingService` and `cosine_similarity` helper.

See plan: /Users/bdogellis/.claude/plans/yes-i-like-this-snoopy-karp.md
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Sequence

import numpy as np

from prolific.agent.nodes.cross_check import cosine_similarity
from prolific.core.config import settings
from prolific.services.embedding import get_embedding_service

logger = logging.getLogger(__name__)


_CHANNEL_SUFFIX_RE = re.compile(
    r"\s*\|\s*(sleep history|sleep history narration|relaxing history|"
    r"relaxing sleep history narration|relaxing history narration|"
    r"relaxing history narration for sleep|fall asleep to history|"
    r"sleep story|epic sleep story|documentary for sleep|history for sleep|"
    r"a lost civilizations sleep documentary).*$",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_title(text: str) -> str:
    """Normalize a title for exact-match comparison (Phase A prefilter).

    Strips channel suffixes (`| Sleep History Narration`), punctuation, casing,
    and collapses whitespace. Two titles that normalize to the same string are
    treated as exact duplicates.
    """
    if not text:
        return ""
    s = _CHANNEL_SUFFIX_RE.sub("", text)
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


@dataclass
class PastTopicEmbedding:
    """A past published video with its cached embedding for dedup comparison."""

    video_id: str
    topic: str
    title: str
    published_at: datetime | None
    embedding: np.ndarray | None  # None when not yet hydrated
    embedding_model_version: str | None = None
    # v2: rich-content fields used by the entity gate and rich embeddings
    script_excerpt: str = ""  # Truncated script_text or description; richer than topic alone
    entities: list[str] = field(default_factory=list)  # Canonical entity names from LLM extraction


@dataclass
class EntityOverlapResult:
    """Result of running the entity gate on a single candidate."""

    is_dupe: bool
    matched_entity: str | None = None
    matched_video_id: str | None = None
    matched_topic: str | None = None
    matched_published_at: datetime | None = None
    reject_reason: str = ""


@dataclass
class DedupResult:
    """Result of running the dedup gate on a single candidate."""

    is_dupe: bool
    in_warn_band: bool = False
    similarity: float = 0.0
    most_similar_topic: str | None = None
    most_similar_video_id: str | None = None
    most_similar_published_at: datetime | None = None
    reject_reason: str = ""

    # Top-3 most similar past videos (for anti-gaming continuation validation)
    top_matches: list[tuple[str, str, float]] = field(default_factory=list)
    # ^ list of (video_id, topic, similarity)


def _composite_text(topic: str, supporting_text: str = "", cap_chars: int = 200) -> str:
    """Build the string we embed for a CANDIDATE (sparse — no script yet).

    Topic alone is too short and shares too much vocabulary across history
    figures. Concatenating with appeal_reason / hook_angle gives the embedding
    more semantic surface. Cap supporting text at `cap_chars` to prevent the
    LLM gaming similarity by stuffing context into appeal_reason.
    """
    topic = (topic or "").strip()
    extra = (supporting_text or "").strip()[:cap_chars]
    if extra:
        return f"{topic} | {extra}"
    return topic


def _rich_composite_text(topic: str, supporting_text: str, script_excerpt: str) -> str:
    """Build the RICH composite for past records (we have the script).

    v2 dedup embeds past records as topic+hook+script_excerpt — gives the
    embedding direct access to the actual narration vocabulary. Catches cases
    where the LLM rephrased the topic title to evade the v1 dedup gate.

    Excerpt is truncated to settings.topic_dedup_script_excerpt_chars upstream.
    """
    parts = [(topic or "").strip()]
    if supporting_text:
        parts.append(supporting_text.strip()[:200])
    if script_excerpt:
        max_chars = settings.topic_dedup_script_excerpt_chars
        parts.append(script_excerpt.strip()[:max_chars])
    return " | ".join(p for p in parts if p)


def _expected_model_version() -> str:
    """The full version string stored in DB; bumping the marker forces re-hydrate."""
    return f"{settings.embedding_model}:{settings.topic_dedup_composite_marker}"


_GENERIC_ENTITY_STOPLIST = {
    "animal", "animals", "person", "people", "human", "humans", "fact", "facts",
    "story", "history", "video", "topic", "thing", "things", "stuff",
    "world", "earth", "life", "time", "day", "night", "year", "years",
}


class _EntityResult(__import__("pydantic").BaseModel):
    """Structured-output schema for the entity-extraction LLM call."""
    entities: list[str]


_ENTITY_EXTRACTION_PROMPT = """Extract the main subject(s) of the following content as canonical noun phrases.

Return at most 3 canonical entity names that uniquely identify what this content is ABOUT.
Use the SAME canonical name regardless of how the entity is described in the source text.

Examples:
- "the bird with a death tongue inside its skull" → ["woodpecker"]
- "the dangerous fruit that literally eats you back" → ["pineapple", "bromelain"]
- "Cyrus II of Persia, founder of Achaemenid Empire" → ["cyrus the great", "achaemenid empire"]
- "exploding tree like a grenade" → ["sandbox tree"]
- "the man who didn't eat for 382 days" → ["angus barbieri", "fasting"]
- "centipede that you should never kill in your house" → ["house centipede"]

Rules:
- Lowercased canonical names only
- No generic categories like "animal", "person", "fact", "history" — too broad
- ≤3 entities
- If you can't identify a specific entity, return []

Content:
\"\"\"{text}\"\"\""""


async def entity_extraction(text: str, max_chars: int = 2000) -> list[str]:
    """Extract canonical entity names from arbitrary text via cheap LLM call.

    Used both at hydration time (on past video script_text/description) and at
    candidate-evaluation time (on today's topic+hook). The LLM resolves rephrased
    descriptions to canonical entities ("bird with death tongue" → "woodpecker")
    using world knowledge.

    Returns lowercased list of canonical entity strings, ≤max_entities, with
    generic stoplist words filtered. Returns [] on API failure (fail-open).
    """
    if not text or not text.strip():
        return []

    # Cap input length so we don't burn tokens on full long-form scripts.
    text = text.strip()[:max_chars]

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from prolific.services.llm import get_llm_service

        llm_service = get_llm_service()
        result = await llm_service.invoke_with_structured_output(
            messages=[
                SystemMessage(content=_ENTITY_EXTRACTION_PROMPT.format(text=text)),
                HumanMessage(content="Extract entities now."),
            ],
            output_schema=_EntityResult,
            tier="research",
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("DEDUP entity_extraction failed for '%s...': %s — failing open", text[:60], exc)
        return []

    cleaned: list[str] = []
    for e in (result.entities or [])[: settings.topic_dedup_max_entities_per_video]:
        if not isinstance(e, str):
            continue
        norm = e.strip().lower()
        if not norm or norm in _GENERIC_ENTITY_STOPLIST:
            continue
        cleaned.append(norm)
    return cleaned


def check_entity_overlap(
    candidate_entities: list[str],
    past: Sequence[PastTopicEmbedding],
    cooldown_days: int,
    now: datetime | None = None,
) -> EntityOverlapResult:
    """Hard-block any candidate whose entity matches a past video within cooldown.

    Set-membership comparison (not fuzzy). Catches LLM-rephrased entity-rename
    evasion that the cosine gate misses (e.g., "bird with deadly harpoon" vs
    past "woodpecker tongue secret" — same entity per LLM, but cosine 0.59).

    Past records older than `cooldown_days` are ignored (entity has gone stale).
    """
    if not candidate_entities or not past:
        return EntityOverlapResult(is_dupe=False)

    cand_set = {e.lower().strip() for e in candidate_entities if e}
    cand_set -= _GENERIC_ENTITY_STOPLIST
    if not cand_set:
        return EntityOverlapResult(is_dupe=False)

    now = now or datetime.now(timezone.utc)
    for past_item in past:
        if not past_item.entities:
            continue
        # Cooldown check
        if past_item.published_at is not None:
            pub = past_item.published_at
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            age_days = (now - pub).total_seconds() / 86400
            if age_days > cooldown_days:
                continue
        past_set = {e.lower().strip() for e in past_item.entities if e}
        overlap = cand_set & past_set
        if overlap:
            matched = next(iter(overlap))
            logger.info(
                "DEDUP REJECTED entity overlap: '%s' matches past video '%s' [%s]",
                matched, past_item.topic[:60], past_item.video_id,
            )
            return EntityOverlapResult(
                is_dupe=True,
                matched_entity=matched,
                matched_video_id=past_item.video_id,
                matched_topic=past_item.topic,
                matched_published_at=past_item.published_at,
                reject_reason=f"entity '{matched}' overlaps past video '{past_item.topic}' ({past_item.video_id})",
            )

    return EntityOverlapResult(is_dupe=False)


def check_dedup(
    candidate_topic: str,
    candidate_supporting_text: str,
    candidate_embedding: np.ndarray | None,
    past: Sequence[PastTopicEmbedding],
    threshold: float | None = None,
    warn_band_low: float | None = None,
) -> DedupResult:
    """Run the semantic dedup gate over past topics.

    `candidate_embedding` should be the embedding of the composite string
    `topic | supporting_text` (built via `_composite_text`). Caller is
    responsible for embedding the candidate (lets us batch multiple candidates
    in one API call upstream).

    Returns DedupResult; does NOT raise on empty `past` (cold start) or on
    candidates with no embedding (the latter signals an upstream embedding
    failure — fail open).
    """
    threshold = threshold if threshold is not None else settings.topic_dedup_threshold
    warn_band_low = (
        warn_band_low if warn_band_low is not None else settings.topic_dedup_warn_band_low
    )

    if not past:
        return DedupResult(is_dupe=False)

    if candidate_embedding is None:
        # Embedding failed upstream — fail open with explicit log
        logger.warning(
            "DEDUP SKIP candidate '%s' has no embedding — failing open (allowing through)",
            candidate_topic[:80],
        )
        return DedupResult(is_dupe=False)

    cand_list = candidate_embedding.tolist() if isinstance(candidate_embedding, np.ndarray) else list(candidate_embedding)

    scored: list[tuple[str, str, float, datetime | None]] = []
    for past_item in past:
        if past_item.embedding is None:
            continue
        past_list = past_item.embedding.tolist() if isinstance(past_item.embedding, np.ndarray) else list(past_item.embedding)
        try:
            sim = cosine_similarity(cand_list, past_list)
        except Exception as exc:
            logger.warning("DEDUP cosine error for '%s' vs past '%s': %s", candidate_topic[:60], past_item.topic[:60], exc)
            continue
        scored.append((past_item.video_id, past_item.topic, sim, past_item.published_at))

    if not scored:
        return DedupResult(is_dupe=False)

    scored.sort(key=lambda x: x[2], reverse=True)
    top_id, top_topic, top_sim, top_pub = scored[0]
    top3 = [(vid, t, s) for (vid, t, s, _p) in scored[:3]]

    if top_sim > threshold:
        logger.info(
            "DEDUP REJECTED '%s' (sim=%.3f > %.2f) ~~ similar to '%s' [%s]",
            candidate_topic[:80], top_sim, threshold, top_topic[:80], top_id,
        )
        return DedupResult(
            is_dupe=True,
            in_warn_band=False,
            similarity=top_sim,
            most_similar_topic=top_topic,
            most_similar_video_id=top_id,
            most_similar_published_at=top_pub,
            reject_reason=(
                f"semantic similarity {top_sim:.3f} exceeds threshold {threshold:.2f} "
                f"vs past video '{top_topic}' ({top_id})"
            ),
            top_matches=top3,
        )

    in_warn = warn_band_low <= top_sim <= threshold
    if in_warn:
        logger.info(
            "DEDUP WARN BAND '%s' (sim=%.3f in [%.2f, %.2f]) ~~ '%s' [%s]",
            candidate_topic[:80], top_sim, warn_band_low, threshold, top_topic[:80], top_id,
        )

    return DedupResult(
        is_dupe=False,
        in_warn_band=in_warn,
        similarity=top_sim,
        most_similar_topic=top_topic,
        most_similar_video_id=top_id,
        most_similar_published_at=top_pub,
        top_matches=top3,
    )


def validate_continuation(
    continues_video_id: str | None,
    distinct_angle: str | None,
    dedup_result: DedupResult,
    cooldown_days: int,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Validate an `is_intentional_continuation=True` candidate.

    Rules:
      a) `continues_video_id` must be non-empty AND must appear in the top-3
         most-similar past videos (anti-gaming: the LLM can't claim continuation
         of an arbitrary unrelated video).
      b) Original published ≥ cooldown_days ago (or unknown publish date OK).
      c) `distinct_angle` non-empty AND ≥ 20 chars (force genuine angle).
      d) Similarity to claimed parent must be ≥ threshold; if low, flag was
         unnecessary — log warn but DO NOT fail (don't fail-close on this).

    Returns (is_valid, reason). On reject, reason is human-readable.
    """
    now = now or datetime.now(timezone.utc)

    if not continues_video_id:
        return False, "is_intentional_continuation=True but continues_video_id is empty"

    if not distinct_angle or len(distinct_angle.strip()) < 20:
        return False, (
            "distinct_angle must be non-empty and ≥20 chars "
            f"(got {len(distinct_angle.strip()) if distinct_angle else 0} chars)"
        )

    top3_ids = [vid for (vid, _t, _s) in dedup_result.top_matches]
    if continues_video_id not in top3_ids:
        return False, (
            f"continues_video_id '{continues_video_id}' is not in top-3 most-similar "
            f"past videos {top3_ids} — likely hallucinated reference"
        )

    parent_pub = dedup_result.most_similar_published_at
    if parent_pub is not None:
        if parent_pub.tzinfo is None:
            parent_pub = parent_pub.replace(tzinfo=timezone.utc)
        age_days = (now - parent_pub).total_seconds() / 86400
        if age_days < cooldown_days:
            return False, (
                f"parent video published {age_days:.1f} days ago, "
                f"cooldown is {cooldown_days} days"
            )

    # Anti-gaming check (d): if claimed similarity to parent is low, the flag
    # wasn't needed. Log warning but allow through — don't fail-close.
    parent_sim = next(
        (s for (vid, _t, s) in dedup_result.top_matches if vid == continues_video_id),
        0.0,
    )
    threshold = settings.topic_dedup_threshold
    if parent_sim < threshold:
        logger.warning(
            "CONTINUATION FLAG SUSPICIOUS: parent_sim=%.3f < threshold=%.2f for parent %s "
            "— flag was unnecessary, allowing through anyway",
            parent_sim, threshold, continues_video_id,
        )

    return True, "valid continuation"


def embedding_to_blob(vec: list[float] | np.ndarray) -> bytes:
    """Serialize a 1536-dim embedding to compact bytes for SQLite BLOB storage.

    Float32 (not float64) — sufficient precision for cosine, halves storage.
    1536 floats × 4 bytes = 6144 bytes per row.
    """
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def blob_to_embedding(blob: bytes | None) -> np.ndarray | None:
    """Deserialize a BLOB back to a numpy float32 array. Returns None on null/empty."""
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32)


async def hydrate_embeddings(
    records: list[PastTopicEmbedding],
    composite_text_for_record: Callable[[PastTopicEmbedding], str],
    persist_callback: Callable[[str, np.ndarray, str], Awaitable[None]],
    persist_entities_callback: Callable[[str, list[str]], Awaitable[None]] | None = None,
) -> list[PastTopicEmbedding]:
    """Embed any records missing cached embeddings, persist to DB, return all hydrated.

    `composite_text_for_record` builds the string-to-embed from a record (lets
    long-form and shorts use different fields). For v2, callers should build a
    rich composite via `_rich_composite_text(topic, supporting, script_excerpt)`.

    `persist_callback(video_id, embedding, model_version)` writes the embedding
    back to the appropriate DB table.

    `persist_entities_callback(video_id, entities)` writes extracted entities back
    to DB. If provided AND `topic_dedup_entity_gate_enabled`, entities are extracted
    via LLM for any record that has no entities cached yet.

    Fails open: if the embedding API call fails, the records still come back —
    just with `embedding=None` on the failed ones. Caller's gate must handle
    None embeddings gracefully.
    """
    expected_version = _expected_model_version()
    needs_embedding = [
        r for r in records
        if r.embedding is None or r.embedding_model_version != expected_version
    ]
    needs_entities = [
        r for r in records
        if not r.entities and r.script_excerpt
    ] if (persist_entities_callback is not None and settings.topic_dedup_entity_gate_enabled) else []

    if not needs_embedding and not needs_entities:
        return records

    if needs_embedding:
        logger.info(
            "DEDUP hydrating %d/%d past records (rich composite, version=%s)",
            len(needs_embedding), len(records), expected_version,
        )
        texts = [composite_text_for_record(r) for r in needs_embedding]
        try:
            embedding_service = get_embedding_service()
            vectors = await embedding_service.embed_texts(texts)
        except Exception as exc:
            logger.warning(
                "DEDUP hydration failed (embedding API error: %s) — gate will fail-open for unhydrated records",
                exc,
            )
            vectors = [None] * len(needs_embedding)

        by_id = {r.video_id: r for r in records}
        for record, vec in zip(needs_embedding, vectors):
            if vec is None:
                continue
            arr = np.asarray(vec, dtype=np.float32)
            record.embedding = arr
            record.embedding_model_version = expected_version
            if record.video_id in by_id:
                by_id[record.video_id].embedding = arr
                by_id[record.video_id].embedding_model_version = expected_version
            try:
                await persist_callback(record.video_id, arr, expected_version)
            except Exception as exc:
                logger.warning(
                    "DEDUP failed to persist embedding for %s: %s (continuing)",
                    record.video_id, exc,
                )

    if needs_entities:
        logger.info(
            "DEDUP entity-extracting %d/%d past records",
            len(needs_entities), len(records),
        )
        by_id = {r.video_id: r for r in records}
        for record in needs_entities:
            try:
                ents = await entity_extraction(record.script_excerpt or record.topic)
            except Exception as exc:
                logger.warning(
                    "DEDUP entity extraction failed for %s: %s (continuing)",
                    record.video_id, exc,
                )
                continue
            record.entities = ents
            if record.video_id in by_id:
                by_id[record.video_id].entities = ents
            try:
                await persist_entities_callback(record.video_id, ents)
            except Exception as exc:
                logger.warning(
                    "DEDUP failed to persist entities for %s: %s (continuing)",
                    record.video_id, exc,
                )

    return records


# Public entry-point for embedding a single candidate composite string.
# Async wrapper around `embed_text` for use inside topic_selection nodes.
async def embed_candidate(topic: str, supporting_text: str = "") -> np.ndarray | None:
    """Embed a single candidate. Returns None on API failure (fail-open downstream)."""
    text = _composite_text(topic, supporting_text)
    try:
        embedding_service = get_embedding_service()
        vec = await embedding_service.embed_text(text)
        return np.asarray(vec, dtype=np.float32)
    except Exception as exc:
        logger.warning("DEDUP failed to embed candidate '%s': %s — failing open", topic[:80], exc)
        return None


async def embed_candidates_batch(
    candidates: list[tuple[str, str]],
) -> list[np.ndarray | None]:
    """Embed multiple candidates in one API call.

    `candidates` is a list of (topic, supporting_text) tuples. Returns a list
    of numpy arrays (or None entries on full-batch failure).
    """
    if not candidates:
        return []
    texts = [_composite_text(t, s) for (t, s) in candidates]
    try:
        embedding_service = get_embedding_service()
        vectors = await embedding_service.embed_texts(texts)
        return [np.asarray(v, dtype=np.float32) for v in vectors]
    except Exception as exc:
        logger.warning(
            "DEDUP batch embedding failed for %d candidates: %s — failing open for all",
            len(candidates), exc,
        )
        return [None] * len(candidates)


def build_rejection_feedback(
    rejected: list[tuple[str, DedupResult]],
) -> list[str]:
    """Build the `past_topics`-style feedback lines for the retry brainstorm prompt.

    Format: `"- {past_topic} (you suggested something too close to this — pick a structurally different subject)"`
    Returns one line per rejected candidate, deduplicated by past topic.
    """
    seen: set[str] = set()
    lines: list[str] = []
    for _candidate_topic, result in rejected:
        if not result.most_similar_topic:
            continue
        key = result.most_similar_topic
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"- {result.most_similar_topic} (you suggested something too close to this — "
            f"pick a structurally different subject)"
        )
    return lines
