"""Real cost tracking using 11Labs and OpenRouter APIs."""

import logging
from dataclasses import dataclass, field

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class CostSnapshot:
    elevenlabs_credits_used: int = 0
    elevenlabs_credits_limit: int = 0
    elevenlabs_credits_remaining: int = 0
    elevenlabs_tier: str = ""
    openrouter_usage_usd: float = 0.0
    openrouter_daily_usd: float = 0.0
    openrouter_monthly_usd: float = 0.0
    openrouter_limit_remaining: float | None = None


@dataclass
class PipelineRunCost:
    elevenlabs_credits_before: int = 0
    elevenlabs_credits_after: int = 0
    elevenlabs_credits_used: int = 0
    elevenlabs_tier: str = ""
    elevenlabs_credits_remaining: int = 0
    openrouter_usd_before: float = 0.0
    openrouter_usd_after: float = 0.0
    openrouter_usd_used: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        lines = ["--- REAL COST TRACKING ---"]
        lines.append(f"  11Labs credits used: {self.elevenlabs_credits_used:,}")
        lines.append(f"  11Labs remaining: {self.elevenlabs_credits_remaining:,} ({self.elevenlabs_tier})")
        lines.append(f"  OpenRouter cost: ${self.openrouter_usd_used:.4f}")
        if self.errors:
            lines.append(f"  Tracking errors: {', '.join(self.errors)}")
        return "\n".join(lines)


async def get_elevenlabs_usage() -> tuple[int, int, str]:
    """Get current 11Labs credit usage. Returns (credits_used, credits_limit, tier)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{ELEVENLABS_BASE_URL}/user/subscription",
                headers={"xi-api-key": settings.elevenlabs_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return (
                data.get("character_count", 0),
                data.get("character_limit", 0),
                data.get("tier", "unknown"),
            )
    except Exception as e:
        logger.warning(f"Failed to fetch 11Labs usage: {e}")
        return 0, 0, "error"


async def get_openrouter_usage() -> tuple[float, float, float]:
    """Get OpenRouter usage. Returns (total_usd, daily_usd, monthly_usd)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{OPENROUTER_BASE_URL}/key",
                headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
            return (
                data.get("usage", 0.0),
                data.get("usage_daily", 0.0),
                data.get("usage_monthly", 0.0),
            )
    except Exception as e:
        logger.warning(f"Failed to fetch OpenRouter usage: {e}")
        return 0.0, 0.0, 0.0


async def snapshot_before() -> dict:
    """Take a cost snapshot before pipeline run."""
    el_used, el_limit, el_tier = await get_elevenlabs_usage()
    or_total, or_daily, or_monthly = await get_openrouter_usage()
    return {
        "elevenlabs_credits_used": el_used,
        "elevenlabs_credits_limit": el_limit,
        "elevenlabs_tier": el_tier,
        "openrouter_total_usd": or_total,
        "openrouter_daily_usd": or_daily,
    }


async def snapshot_after(before: dict) -> PipelineRunCost:
    """Take a cost snapshot after pipeline run and compute deltas."""
    el_used, el_limit, el_tier = await get_elevenlabs_usage()
    or_total, or_daily, or_monthly = await get_openrouter_usage()

    cost = PipelineRunCost(
        elevenlabs_credits_before=before["elevenlabs_credits_used"],
        elevenlabs_credits_after=el_used,
        elevenlabs_credits_used=el_used - before["elevenlabs_credits_used"],
        elevenlabs_tier=el_tier,
        elevenlabs_credits_remaining=el_limit - el_used,
        openrouter_usd_before=before["openrouter_total_usd"],
        openrouter_usd_after=or_total,
        openrouter_usd_used=or_total - before["openrouter_total_usd"],
    )

    errors = []
    if before.get("elevenlabs_tier") == "error":
        errors.append("11Labs pre-snapshot failed")
    if el_tier == "error":
        errors.append("11Labs post-snapshot failed")
    cost.errors = errors

    return cost
