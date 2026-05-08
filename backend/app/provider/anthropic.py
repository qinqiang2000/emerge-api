from __future__ import annotations

from typing import Any

import httpx

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    ProviderResult,
    TextBlock,
)
from app.provider.retry import RetryableError, retry_async


_API_URL = "https://api.anthropic.com/v1/messages"
_TOOL_NAME = "emit_extraction"


def _block_to_anthropic(b: ContentBlock) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ImageBlock):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": b.media_type, "data": b.data_b64},
        }
    if isinstance(b, DocumentBlock):
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": b.media_type, "data": b.data_b64},
        }
    raise ValueError(f"unknown block type: {b!r}")


class AnthropicProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        timeout: float = 120.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._proxy = proxy
        self._timeout = timeout
        self._retry_max = retry_max_attempts
        self._retry_base = retry_base_delay

    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],
        response_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> ProviderResult:
        params = params or {}
        body = {
            "model": model_id,
            "max_tokens": params.get("max_tokens", 4096),
            "temperature": params.get("temperature", 0.0),
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": [_block_to_anthropic(b) for b in user_content],
                }
            ],
            "tools": [
                {
                    "name": _TOOL_NAME,
                    "description": "Emit the structured extraction result.",
                    "input_schema": response_schema,
                }
            ],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async def _call() -> ProviderResult:
            client_kwargs: dict[str, Any] = {"timeout": self._timeout, "trust_env": False}
            if self._proxy:
                client_kwargs["proxy"] = self._proxy
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.post(_API_URL, json=body, headers=headers)
                if resp.status_code in (429, 502, 503, 504):
                    raise RetryableError(f"anthropic {resp.status_code}: {resp.text[:200]}")
                resp.raise_for_status()
                data = resp.json()
            tool_use = next(
                (c for c in data.get("content", []) if c.get("type") == "tool_use"),
                None,
            )
            if tool_use is None:
                raise RuntimeError(f"no tool_use in anthropic response: {data}")
            usage = data.get("usage", {})
            return ProviderResult(
                raw_json=tool_use["input"],
                model_id=data.get("model", model_id),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
