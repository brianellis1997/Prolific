"""LLM provider abstraction for tiered model usage.

Supports OpenRouter for access to multiple models with cost optimization:
- Cheap models (GPT-4o-mini, Haiku) for research/extraction
- Premium models (Sonnet) for writing
"""

import logging
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI

from prolific.core.config import settings

logger = logging.getLogger(__name__)

ModelTier = Literal["research", "extraction", "writing", "verification", "vision"]


class LLMService:
    """Service for getting LLM instances with tiered model selection.

    Uses OpenRouter as the backend, selecting appropriate models
    based on the task tier for cost optimization.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        """Initialize LLM service.

        Args:
            api_key: OpenRouter API key (default from config)
            base_url: OpenRouter base URL (default from config)
        """
        self.api_key = api_key or settings.openrouter_api_key
        self.base_url = base_url or settings.openrouter_base_url

        self._model_map = {
            "research": settings.research_model,
            "extraction": settings.extraction_model,
            "writing": settings.writing_model,
            "verification": settings.verification_model,
            "vision": settings.vision_model,
        }

        self._llm_cache: dict[str, ChatOpenAI] = {}

    def get_model_name(self, tier: ModelTier) -> str:
        """Get the model name for a given tier."""
        return self._model_map.get(tier, settings.research_model)

    def get_llm(
        self,
        tier: ModelTier,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatOpenAI:
        """Get an LLM instance for the specified tier.

        Args:
            tier: Model tier (research, extraction, writing, verification)
            temperature: Sampling temperature (default 0.7)
            max_tokens: Max output tokens (default None = model default)

        Returns:
            ChatOpenAI instance configured for OpenRouter
        """
        model_name = self.get_model_name(tier)
        cache_key = f"{model_name}_{temperature}_{max_tokens}"

        if cache_key not in self._llm_cache:
            kwargs = {
                "api_key": self.api_key,
                "base_url": self.base_url,
                "model": model_name,
                "temperature": temperature,
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens

            self._llm_cache[cache_key] = ChatOpenAI(**kwargs)
            logger.info(f"Created LLM instance: {model_name} (tier={tier})")

        return self._llm_cache[cache_key]

    async def invoke(
        self,
        messages: list[BaseMessage],
        tier: ModelTier,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> BaseMessage:
        """Invoke the LLM with messages.

        Args:
            messages: List of messages to send
            tier: Model tier to use
            temperature: Sampling temperature
            max_tokens: Max output tokens

        Returns:
            AI response message
        """
        llm = self.get_llm(tier, temperature, max_tokens)
        response = await llm.ainvoke(messages)
        self._record_usage(response, tier)
        return response

    def _record_usage(self, response: BaseMessage, tier: ModelTier):
        try:
            from prolific.services.usage_tracker import get_usage_tracker
            usage = getattr(response, "response_metadata", {}).get("usage", {})
            if not usage:
                usage = getattr(response, "response_metadata", {}).get("token_usage", {})
            input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
            if input_tokens or output_tokens:
                get_usage_tracker().record_llm_call(
                    self.get_model_name(tier), input_tokens, output_tokens
                )
        except Exception:
            pass

    async def invoke_with_structured_output(
        self,
        messages: list[BaseMessage],
        output_schema: type,
        tier: ModelTier,
        temperature: float = 0.3,
    ) -> Any:
        """Invoke the LLM with structured output.

        Args:
            messages: List of messages to send
            output_schema: Pydantic model for structured output
            tier: Model tier to use
            temperature: Sampling temperature (lower for structured)

        Returns:
            Parsed output matching the schema
        """
        llm = self.get_llm(tier, temperature)
        from prolific.services.usage_tracker import LLMUsageCallbackHandler
        handler = LLMUsageCallbackHandler(model_name=self.get_model_name(tier))
        structured_llm = llm.with_structured_output(output_schema)
        return await structured_llm.ainvoke(messages, config={"callbacks": [handler]})

    async def invoke_with_image(
        self,
        prompt: str,
        image_base64: str,
        image_format: str = "png",
        tier: ModelTier = "vision",
        temperature: float = 0.3,
    ) -> str:
        """Invoke the LLM with an image for multimodal analysis.

        Args:
            prompt: Text prompt describing what to analyze
            image_base64: Base64-encoded image data
            image_format: Image format (png, jpg, webp)
            tier: Model tier to use (defaults to vision)
            temperature: Sampling temperature

        Returns:
            Model's text response about the image
        """
        from langchain_core.messages import HumanMessage

        mime_type = f"image/{image_format}"
        if image_format == "jpg":
            mime_type = "image/jpeg"

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}",
                    },
                },
            ]
        )

        llm = self.get_llm(tier, temperature)
        response = await llm.ainvoke([message])
        self._record_usage(response, tier)
        return response.content

    async def invoke_with_image_structured(
        self,
        prompt: str,
        image_base64: str,
        output_schema: type,
        image_format: str = "png",
        tier: ModelTier = "vision",
        temperature: float = 0.3,
    ) -> Any:
        """Invoke the LLM with an image and get structured output.

        Args:
            prompt: Text prompt describing what to analyze
            image_base64: Base64-encoded image data
            output_schema: Pydantic model for structured output
            image_format: Image format (png, jpg, webp)
            tier: Model tier to use (defaults to vision)
            temperature: Sampling temperature

        Returns:
            Parsed output matching the schema
        """
        from langchain_core.messages import HumanMessage

        mime_type = f"image/{image_format}"
        if image_format == "jpg":
            mime_type = "image/jpeg"

        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{image_base64}",
                    },
                },
            ]
        )

        llm = self.get_llm(tier, temperature)
        from prolific.services.usage_tracker import LLMUsageCallbackHandler
        handler = LLMUsageCallbackHandler(model_name=self.get_model_name(tier))
        structured_llm = llm.with_structured_output(output_schema)
        return await structured_llm.ainvoke([message], config={"callbacks": [handler]})


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get the singleton LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
