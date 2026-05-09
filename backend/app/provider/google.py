"""Google Gemini provider adapter — Extract LLM, separate from claude_agent_sdk."""
from __future__ import annotations

import json
from typing import Any

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    ProviderResult,
    TextBlock,
)
from app.provider.retry import RetryableError, retry_async


class GoogleProvider(Provider):
    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        timeout: float = 120.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        # Lazy import so test environments without google-genai still load the module.
        from google import genai
        from google.genai.types import HttpOptions

        # trust_env=False so we don't accidentally inherit CLAUDE_PROXY (SOCKS5,
        # intended for the Claude agent SDK only). If a Google-side proxy is needed,
        # caller passes it explicitly via the `proxy` argument.
        client_args: dict[str, Any] = {"trust_env": False}
        if proxy:
            client_args["proxy"] = proxy
        self._client = genai.Client(
            api_key=api_key,
            http_options=HttpOptions(client_args=client_args, async_client_args=client_args),
        )
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
        from google.genai import types

        params = params or {}
        parts: list[Any] = []
        for block in user_content:
            if isinstance(block, TextBlock):
                parts.append(types.Part.from_text(text=block.text))
            elif isinstance(block, ImageBlock):
                import base64

                data = base64.b64decode(block.data_b64)
                parts.append(types.Part.from_bytes(data=data, mime_type=block.media_type))
            elif isinstance(block, DocumentBlock):
                import base64

                data = base64.b64decode(block.data_b64)
                parts.append(types.Part.from_bytes(data=data, mime_type=block.media_type))
            else:
                raise ValueError(f"unknown block type: {block!r}")

        async def _call() -> ProviderResult:
            try:
                resp = await self._client.aio.models.generate_content(
                    model=model_id,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        response_mime_type="application/json",
                        response_schema=response_schema,
                        temperature=params.get("temperature", 0.0),
                    ),
                )
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                if "rate" in msg or "429" in msg or "503" in msg or "504" in msg or "timeout" in msg:
                    raise RetryableError(str(e)) from e
                raise

            if not resp.text:
                raise RuntimeError(f"empty response from gemini: {resp!r}")
            return ProviderResult(
                raw_json=json.loads(resp.text),
                model_id=model_id,
                input_tokens=getattr(resp.usage_metadata, "prompt_token_count", 0) or 0,
                output_tokens=getattr(resp.usage_metadata, "candidates_token_count", 0) or 0,
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
