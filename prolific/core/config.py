"""Application configuration using Pydantic BaseSettings."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API
    api_title: str = "Prolific Content Generation API"
    api_version: str = "0.1.0"
    api_prefix: str = "/api/v1"

    # LLM Configuration
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Tiered Model Selection (cost optimization)
    # Fast/cheap models for research, extraction, verification
    # Max retry attempts on the LLM service for transient errors (timeouts,
    # rate limits, malformed JSON, pydantic validation failures). 5 = one
    # initial call + 4 retries with exponential backoff (4s → 8s → 16s → 32s →
    # cap 60s). Each retried call is logged at WARNING. Bumped from 3 → 5 on
    # 2026-05-27 after a JSONDecodeError in section 6 of a 15-section
    # IMMERSIVE_DAILY_LIFE script killed the whole run.
    llm_max_retry_attempts: int = 5

    research_model: str = "google/gemini-3-flash-preview"
    extraction_model: str = "google/gemini-3-flash-preview"
    verification_model: str = "google/gemini-3-flash-preview"
    # High quality model for writing
    writing_model: str = "anthropic/claude-sonnet-4.5"
    # Multimodal model for vision tasks (image evaluation, diagram understanding)
    vision_model: str = "google/gemini-3-flash-preview"

    # Embeddings
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536

    # Web Search
    tavily_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./prolific.db"

    # ChromaDB
    chroma_persist_path: str = "./chroma_data"

    # Workflow Limits
    max_research_iterations: int = 5
    max_sources_per_topic: int = 20
    max_claims_per_source: int = 50
    max_concurrent_extractions: int = 5
    max_concurrent_writers: int = 3

    # Token Budgets for RAG
    book_memory_budget: int = 2000
    draft_chunk_budget: int = 1500
    evidence_budget: int = 4000

    # Cross-check configuration
    cross_check_similarity_threshold: float = 0.75  # Min similarity for LLM check
    cross_check_corroboration_threshold: float = 0.85  # High similarity = corroboration
    cross_check_max_llm_comparisons: int = 100  # Max LLM calls for conflict detection

    # Topic Deduplication (semantic dedup gate for both pipelines)
    # v2 (2026-04-30): tightened thresholds (0.78 → 0.75) and added entity gate
    # after pineapple+woodpecker rephrased-entity duplicates slipped through v1.
    topic_dedup_enabled: bool = True
    topic_dedup_threshold: float = 0.75  # Reject if cosine sim > threshold and not flagged as continuation
    topic_dedup_warn_band_low: float = 0.65  # Log-only band between this and threshold
    topic_dedup_max_past_topics: int = 200  # Past topics to consider for dedup
    topic_dedup_continuation_cooldown_days: int = 30  # Long-form: min days before sequel allowed
    shorts_continuation_cooldown_days: int = 14  # Shorts: tighter cooldown (4-5 uploads/day)
    # Entity gate (catches LLM-rephrased entity-rename evasion)
    topic_dedup_entity_gate_enabled: bool = True  # Independent kill switch
    topic_dedup_script_excerpt_chars: int = 1500  # Truncate past scripts for richer embeddings
    topic_dedup_max_entities_per_video: int = 3  # Cap LLM-extracted entity count
    # Entity cooldown is INTENTIONALLY longer than continuation_cooldown — a Part 2
    # is fine after 30d, but reusing the same entity (e.g. "pineapple") within 60d
    # is a dupe regardless of intent. Pineapple slipped through at 15d gap because
    # we used continuation_cooldown=14 for both.
    topic_dedup_entity_cooldown_days: int = 60
    # Bumping this string forces re-hydration of all cached embeddings on next run.
    topic_dedup_composite_marker: str = "rich-v1"

    # Generation defaults
    default_depth: Literal["overview", "standard", "deep", "exhaustive"] = "standard"
    default_style_tone: Literal[
        "academic", "conversational", "technical", "journalistic"
    ] = "academic"

    # YouTube Pipeline
    youtube_script_model: str = "google/gemini-3-flash-preview"
    youtube_image_model: str = "google/gemini-3.1-flash-image-preview"
    # Length target: 3hr / ~20K words / 15 sections (rebalanced 2026-05-12).
    # Previously 10K/8 since 2026-03-28 commit 2d60e40, which had panic-cut the
    # original 30K/18 default to dodge a Railway-side issue with the longer
    # pipeline runs. At 1hr we were undersized vs the sleep-history niche (top
    # competitors ship 2-3hr standard). At 100 wpm narration, 20K words ≈ 3hr,
    # matching the niche's watch-time-per-click leaders.
    # NB: youtube_max_images doubles as the section count via
    # script_planning.py:35 (num_sections = settings.youtube_max_images).
    # Keep words_per_section ≈ 1,333 for writer coherence — same as before.
    youtube_target_word_count: int = 20000
    youtube_max_images: int = 15
    # "Sleep loop" — every long-form upload is added to this one playlist so the
    # videos autoplay into one another. For a sleeping audience, autoplay (which
    # requires no action) is the real session-time lever; end screens need a
    # click the viewer is asleep for, so we skip those. Added 2026-06-12 after
    # Studio flagged keeping the sleep loop going. Empty string disables.
    youtube_series_playlist_title: str = "Ancient Mysteries & Lost Civilizations — Sleep Documentaries"
    youtube_image_style: str = "oil painting, historical illustration, warm muted tones, cinematic lighting"
    youtube_output_dir: str = "./youtube_output"
    youtube_history_db_path: str = "/app/data/youtube_history.sqlite"
    youtube_biography_ratio: float = 0.7

    # Vision check on the rendered thumbnail catches diffusion-model failures
    # (split words like "HO W" instead of "HOW", dropped letters, garbled glyphs).
    # On failure, the pipeline retries image generation with an intensified prompt
    # naming the specific failure. 2 = one initial render + one retry. Cap is low
    # because cost is image-gen ($0.02/call) not the vision check ($0.0002).
    youtube_thumbnail_max_verify_attempts: int = 2

    # Competitor channels scraped at brainstorm time for click-inspiration.
    # Comma-separated channel IDs (UC...). Pipeline fetches latest N uploads from each
    # via YT Data API and injects titles + view counts into the brainstorm prompt.
    # Defaults to the two closest sleep-history competitors; override via env var if needed.
    youtube_competitor_channel_ids: str = (
        "UC6uGYezl7-dtRlaXohwo5ew,"   # @SleepyTimeHistoryYT — 153K subs, our closest peer
        "UCtKLvGbzqAluwUW3Ez_zeQA"    # @BoringHistorySecrets — 94K subs, "history for sleep" niche
    )
    youtube_competitor_videos_per_channel: int = 8
    # In addition to the fixed competitor channels above, the pipeline also runs YouTube
    # search for trending sleep-history content (view-weighted, filtered to recent uploads)
    # so the brainstorm/title prompts see what's HOT right now, not just stable competitors.
    # Comma-separated queries.
    youtube_niche_search_queries: str = "history for sleep,sleep history,history fall asleep,boring history"
    youtube_niche_search_days: int = 14    # only count uploads from the last N days as "hot"
    youtube_niche_search_per_query: int = 6

    # 11Labs TTS
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_turbo_v2_5"

    # YouTube Data API
    youtube_credentials_path: str = "./youtube_credentials_slumber.json"
    youtube_client_secrets_path: str = "./client_secrets.json"
    shorts_credentials_path: str = "./youtube_credentials.json"
    youtube_default_privacy: str = "public"
    youtube_category_id: str = "27"

    # Scheduler — long-form fires daily at 18:00 ET (Mon/Wed/Fri=BIO, Thu=LOSTCIV, Sat=IMMERSIVE).
    # The Railway env var YOUTUBE_CRON_HOUR overrides this default; the source default is kept
    # in sync with prod intent so a fresh deploy without the env var still fires at 6 PM.
    youtube_cron_hour: int = 18
    youtube_cron_minute: int = 0
    youtube_cron_timezone: str = "America/New_York"
    youtube_cron_enabled: bool = False
    # DAILY cadence (bumped 2026-06-12 — 11Labs growing_business plan (2.9M
    # chars/mo) was only 62% utilized at 5/week (~1.8M used last cycle); ~1.1M
    # credits/mo were going unused. 7/week projects to ~2.5M (~87%) — fits with
    # buffer. (2/day would be ~3.6M, over cap — do not exceed 7/week long-form.)
    # Mix keeps the proven winner weighted: per full 2-month data (n=36) LOSTCIV
    # avg 260 views / 25% retention / 29 subs >> IMMERSIVE 88v/22%/12 >> BIO
    # 63v/18%/6 (BIO cut 2026-06-03). New mix: 6 LOSTCIV / 1 IMMERSIVE / 0 BIO:
    #   Mon-Thu+Sat-Sun=LOSTCIV (6), Fri=IMMERSIVE (1 variety hedge). All 18:00 ET.
    # Reversible by editing these strings; no migration. 11Labs cost $0 extra
    # (flat plan under cap); OpenRouter ~+$8/mo.
    youtube_bio_enabled: bool = False
    youtube_lostciv_enabled: bool = True
    youtube_immersive_enabled: bool = True
    youtube_bio_cron_day: str = "mon"
    youtube_lostciv_cron_day: str = "mon,tue,wed,thu,sat,sun"
    youtube_immersive_cron_day: str = "fri"

    # Shorts Pipeline
    shorts_script_model: str = "google/gemini-3-flash-preview"
    shorts_image_model: str = "google/gemini-3.1-flash-image-preview"
    shorts_target_duration_seconds: int = 28
    shorts_num_visuals: int = 10
    shorts_image_style: str = "bold digital art, dramatic lighting, vibrant colors, 9:16 portrait composition"
    shorts_output_dir: str = "./shorts_output"
    shorts_history_db_path: str = "/app/data/shorts_history.sqlite"
    shorts_crossfade_duration: float = 0.3
    shorts_caption_font_size: int = 48
    shorts_caption_words_per_group: int = 4

    # Shorts TTS (separate energetic voice)
    elevenlabs_shorts_voice_id: str = ""
    elevenlabs_shorts_stability: float = 0.5
    elevenlabs_shorts_similarity_boost: float = 0.75
    elevenlabs_shorts_style: float = 0.4

    # Shorts Scheduler
    shorts_cron_interval_hours: int = 4
    shorts_cron_enabled: bool = False
    # Cadence: cut 4/day -> 2/day after the 5/18 throttle, then raised to 3/day
    # on 2026-06-12 once the recovery proved durable (2 weeks of stable 900-2,200
    # feed views/day, subs 66->94). The diversity guards (cluster gate, opener
    # variance, weighted category rotation) now prevent the over-saturation that
    # caused the original throttle, so 3/day is safe; shorts are ~620 chars each
    # so 11Labs cost is negligible. DO NOT jump straight to 4/day — that was the
    # throttle level; earn it back with clean 3/day data first. Override via env
    # var (comma-separated ET hours). 10/15/20 = morning, afternoon, evening.
    shorts_cron_hours: str = "10,15,20"

    # ---- Shorts diversity guards (post-throttle hardening) ----
    # Cluster-level dedup: extracts thematic cluster tags (e.g. "parasites",
    # "body-shock") from past scripts via LLM and blocks candidates whose cluster
    # overlaps a past short within cooldown. Catches the failure mode where the
    # entity gate allowed 6 different parasites in 5 days because each had a
    # distinct entity ("toxoplasma" / "screwworm" / "tongue-eating louse") but
    # the cluster was identical.
    shorts_cluster_gate_enabled: bool = True
    shorts_cluster_cooldown_days: int = 7
    shorts_cluster_max_per_video: int = 2

    # Title-opener variance: count how many recent shorts start with the same
    # 2-word stem (e.g. "the terrifying", "your jaw") and reject candidates
    # whose topic would push that count above the threshold. Stops the
    # "The Terrifying X / The Horrifying Y / The Nightmare Z" stem fatigue.
    shorts_opener_variance_enabled: bool = True
    shorts_opener_window_size: int = 7
    shorts_opener_max_repeats_per_window: int = 2

    # Category cycling: forces brainstorm to rotate through content categories
    # so a stretch of all-horror videos can't happen. Cycle is deterministic
    # based on count of published shorts modulo the category list length.
    shorts_category_cycling_enabled: bool = True

    # Comment Reply Scheduler
    comment_reply_enabled: bool = False
    comment_reply_interval_hours: int = 2

    # Kling AI Video (via FAL.ai)
    fal_api_key: str = ""
    kling_enabled: bool = False
    kling_marble_ref_urls: str = ""
    kling_worm_ref_urls: str = ""
    kling_model_endpoint: str = "fal-ai/kling-video/v2.5-turbo/pro/text-to-video"
    kling_image_to_video_endpoint: str = "fal-ai/kling-video/v3/pro/image-to-video"
    kling_video_duration: str = "5"
    kling_max_concurrent: int = 3
    kling_cost_per_sec_usd: float = 0.07
    kling_cron_hours: str = "16"
    kling_cron_days: str = "0,2,4"  # 0=Mon, 2=Wed, 4=Fri
    kling_character_mode: str = "auto"

    # Pexels Video API
    pexels_api_key: str = ""

    # Pixabay Video API
    pixabay_api_key: str = ""

    # Twitch API
    twitch_client_id: str = ""
    twitch_client_secret: str = ""

    # Shorts Content Modes
    shorts_niche: str = "general"  # "twitch", "sports", "celebrity", "curiosity", "general"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
