"""Compute estimated USD costs from API usage data."""

MODEL_PRICING = {
    "google/gemini-3-flash-preview": {"input": 0.10, "output": 0.40},
    "anthropic/claude-sonnet-4.5": {"input": 3.00, "output": 15.00},
}

EMBEDDING_PRICE_PER_M = 0.02  # text-embedding-3-small per 1M tokens
SEARCH_COST_PER_CALL = 0.01


def calculate_costs(usage_summary: dict) -> dict:
    llm_cost = 0.0
    for model, usage in usage_summary.get("llm_by_model", {}).items():
        pricing = MODEL_PRICING.get(model, {"input": 1.0, "output": 3.0})
        llm_cost += (usage["input_tokens"] / 1_000_000) * pricing["input"]
        llm_cost += (usage["output_tokens"] / 1_000_000) * pricing["output"]

    embedding_cost = (usage_summary.get("embedding_tokens", 0) / 1_000_000) * EMBEDDING_PRICE_PER_M
    search_cost = usage_summary.get("search_calls", 0) * SEARCH_COST_PER_CALL

    return {
        "llm_input_tokens": usage_summary.get("llm_input_tokens", 0),
        "llm_output_tokens": usage_summary.get("llm_output_tokens", 0),
        "llm_cost_usd": round(llm_cost, 4),
        "embedding_tokens": usage_summary.get("embedding_tokens", 0),
        "embedding_cost_usd": round(embedding_cost, 4),
        "search_calls": usage_summary.get("search_calls", 0),
        "search_cost_usd": round(search_cost, 4),
        "total_cost_usd": round(llm_cost + embedding_cost + search_cost, 4),
    }
