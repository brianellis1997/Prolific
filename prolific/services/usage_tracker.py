"""Global API usage tracking for cost monitoring."""

import logging
import threading
from dataclasses import dataclass, field

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)


@dataclass
class ModelUsage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    call_count: int = 0


@dataclass
class UsageTracker:
    llm_usage: dict[str, ModelUsage] = field(default_factory=dict)
    embedding_tokens: int = 0
    embedding_calls: int = 0
    search_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_llm_call(self, model: str, input_tokens: int, output_tokens: int):
        with self._lock:
            if model not in self.llm_usage:
                self.llm_usage[model] = ModelUsage(model=model)
            self.llm_usage[model].input_tokens += input_tokens
            self.llm_usage[model].output_tokens += output_tokens
            self.llm_usage[model].call_count += 1

    def record_embedding_call(self, token_count: int):
        with self._lock:
            self.embedding_tokens += token_count
            self.embedding_calls += 1

    def record_search_call(self):
        with self._lock:
            self.search_calls += 1

    def get_summary(self) -> dict:
        with self._lock:
            total_llm_input = sum(u.input_tokens for u in self.llm_usage.values())
            total_llm_output = sum(u.output_tokens for u in self.llm_usage.values())
            return {
                "llm_input_tokens": total_llm_input,
                "llm_output_tokens": total_llm_output,
                "llm_calls": sum(u.call_count for u in self.llm_usage.values()),
                "llm_by_model": {
                    model: {
                        "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens,
                        "call_count": u.call_count,
                    }
                    for model, u in self.llm_usage.items()
                },
                "embedding_tokens": self.embedding_tokens,
                "embedding_calls": self.embedding_calls,
                "search_calls": self.search_calls,
            }

    def reset(self):
        with self._lock:
            self.llm_usage.clear()
            self.embedding_tokens = 0
            self.embedding_calls = 0
            self.search_calls = 0


class LLMUsageCallbackHandler(AsyncCallbackHandler):
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def on_llm_end(self, response, **kwargs):
        try:
            tracker = get_usage_tracker()
            for generation in response.generations:
                for gen in generation:
                    usage = {}
                    if hasattr(gen, "message") and hasattr(gen.message, "response_metadata"):
                        usage = gen.message.response_metadata.get("usage", {})
                        if not usage:
                            usage = gen.message.response_metadata.get("token_usage", {})
                    input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
                    if input_tokens or output_tokens:
                        tracker.record_llm_call(self.model_name, input_tokens, output_tokens)
        except Exception:
            pass


_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker


def reset_usage_tracker():
    global _tracker
    _tracker = UsageTracker()
