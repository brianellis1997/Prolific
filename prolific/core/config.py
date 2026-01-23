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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
