"""Image generation service using Google Nano Banana 2 via OpenRouter."""

import base64
import logging
from pathlib import Path

import httpx

from prolific.core.config import settings

logger = logging.getLogger(__name__)


class ImageGenService:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url
        self.model = settings.youtube_image_model

    async def generate_image(
        self,
        prompt: str,
        output_path: str,
        style_prefix: str | None = None,
    ) -> str:
        """Generate an image and save to disk. Returns the output path."""
        if style_prefix is None:
            style_prefix = settings.youtube_image_style + ". "

        full_prompt = style_prefix + prompt

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": full_prompt,
                        }
                    ],
                    "max_tokens": 4096,
                },
            )
            response.raise_for_status()
            data = response.json()

        message = data["choices"][0]["message"]
        image_data = None

        images = message.get("images", [])
        if images:
            for img in images:
                if isinstance(img, dict) and img.get("type") == "image_url":
                    url = img["image_url"]["url"]
                    if url.startswith("data:"):
                        b64_str = url.split(",", 1)[1]
                        image_data = base64.b64decode(b64_str)
                        break

        if image_data is None:
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part["image_url"]["url"]
                        if url.startswith("data:"):
                            b64_str = url.split(",", 1)[1]
                            image_data = base64.b64decode(b64_str)
                            break
            elif isinstance(content, str) and content.startswith("data:"):
                b64_str = content.split(",", 1)[1]
                image_data = base64.b64decode(b64_str)

        if image_data is None:
            raise ValueError(f"Could not extract image from response. Message keys: {list(message.keys())}")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(image_data)
        logger.info(f"Image saved: {output_path} ({len(image_data)} bytes)")

        return output_path


_image_gen_service: ImageGenService | None = None


def get_image_gen_service() -> ImageGenService:
    global _image_gen_service
    if _image_gen_service is None:
        _image_gen_service = ImageGenService()
    return _image_gen_service
