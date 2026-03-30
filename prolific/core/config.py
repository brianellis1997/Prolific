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

    # Generation defaults
    default_depth: Literal["overview", "standard", "deep", "exhaustive"] = "standard"
    default_style_tone: Literal[
        "academic", "conversational", "technical", "journalistic"
    ] = "academic"

    # YouTube Pipeline
    youtube_script_model: str = "google/gemini-3-flash-preview"
    youtube_image_model: str = "google/gemini-3.1-flash-image-preview"
    youtube_target_word_count: int = 10000
    youtube_max_images: int = 8
    youtube_image_style: str = "oil painting, historical illustration, warm muted tones, cinematic lighting"
    youtube_output_dir: str = "./youtube_output"
    youtube_history_db_path: str = "./youtube_history.sqlite"
    youtube_biography_ratio: float = 0.7

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

    # Scheduler
    youtube_cron_hour: int = 20
    youtube_cron_minute: int = 0
    youtube_cron_timezone: str = "America/New_York"
    youtube_cron_enabled: bool = False

    # Shorts Pipeline
    shorts_script_model: str = "google/gemini-3-flash-preview"
    shorts_image_model: str = "google/gemini-3.1-flash-image-preview"
    shorts_target_duration_seconds: int = 28
    shorts_num_visuals: int = 10
    shorts_image_style: str = "bold digital art, dramatic lighting, vibrant colors, 9:16 portrait composition"
    shorts_output_dir: str = "./shorts_output"
    shorts_history_db_path: str = "./shorts_history.sqlite"
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

    # Comment Reply Scheduler
    comment_reply_enabled: bool = False
    comment_reply_interval_hours: int = 2

    # Pexels Video API
    pexels_api_key: str = ""

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
