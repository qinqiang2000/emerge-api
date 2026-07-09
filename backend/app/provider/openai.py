from __future__ import annotations

import json
from typing import Any

import httpx

from app.provider.base import (
    ContentBlock,
    ImageBlock,
    Provider,
    ProviderResult,
    TextBlock,
)
from app.provider.retry import RetryableError, is_transient, retry_async


_TOOL_NAME = "emit_extraction"


def _chat_completions_url(base_url: str | None) -> str:
    """Resolve the /chat/completions endpoint. Tolerates a base_url given as
    host-root, `…/v1`, or a full `…/chat/completions` (mirrors
    `anthropic._messages_url`)."""
    b = (base_url or "https://api.openai.com/v1").rstrip("/")
    if b.endswith("/chat/completions"):
        return b
    return b + "/chat/completions"


def _block_to_openai(b: ContentBlock) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "text", "text": b.text}
    if isinstance(b, ImageBlock):
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{b.media_type};base64,{b.data_b64}"},
        }
    # DocumentBlock (PDF) is deliberately unhandled: DashScope's OpenAI-compatible
    # `image_url` rejects raw PDF bytes outright ("image format is illegal"), and
    # no other content type carries a document in this API shape. Callers must
    # rasterize PDF pages to images upstream before reaching this adapter.
    raise ValueError(f"unknown block type: {b!r}")


class OpenAIProvider(Provider):
    # `image_url` rejects raw PDF bytes ("The image format is illegal and cannot
    # be opened"). Callers rasterize PDF pages upstream; see `_block_to_openai`.
    supports_pdf = False

    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
        disable_thinking: bool = False,
    ) -> None:
        self._api_key = api_key
        self._proxy = proxy
        self._url = _chat_completions_url(base_url)
        self._timeout = timeout
        self._retry_max = retry_max_attempts
        self._retry_base = retry_base_delay
        # Qwen3.x-style hybrid-thinking models default thinking ON, which
        # REJECTS a forced tool_choice (400: "tool_choice parameter does not
        # support being set to required or object in thinking mode"). Disable
        # it on custom gateways so forced structured extraction works; real
        # api.openai.com is unaffected (no such field, no such default).
        self._disable_thinking = disable_thinking

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
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {"role": "user", "content": [_block_to_openai(b) for b in user_content]}
        )
        body: dict[str, Any] = {
            "model": model_id,
            "temperature": params.get("temperature", 0.0),
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": _TOOL_NAME,
                        "description": "Emit the structured extraction result.",
                        "parameters": response_schema,
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": _TOOL_NAME}},
        }
        if params.get("max_tokens"):
            body["max_tokens"] = params["max_tokens"]
        if params.get("thinking"):
            # Per-model opt-in (params.thinking = {"type": "enabled"}), mirrors
            # the anthropic adapter's shape. Thinking + forced tool_choice are
            # mutually exclusive on DashScope, so this combination will 400 —
            # callers that want thinking must accept tool_choice:auto instead
            # (not implemented here; no current model config asks for both).
            body["enable_thinking"] = True
            body.pop("temperature", None)
        elif self._disable_thinking:
            body["enable_thinking"] = False
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "content-type": "application/json",
        }

        async def _call() -> ProviderResult:
            client_kwargs: dict[str, Any] = {"timeout": self._timeout, "trust_env": False}
            if self._proxy:
                client_kwargs["proxy"] = self._proxy
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.post(self._url, json=body, headers=headers)
                    if resp.status_code in (429, 502, 503, 504):
                        raise RetryableError(f"openai-compat {resp.status_code}: {resp.text[:200]}")
                    resp.raise_for_status()
                    data = resp.json()
            except RetryableError:
                raise
            except Exception as e:  # noqa: BLE001
                if is_transient(e):
                    raise RetryableError(str(e) or type(e).__name__) from e
                raise
            message = data["choices"][0]["message"]
            tool_calls = message.get("tool_calls") or []
            call = next(
                (c for c in tool_calls if c.get("function", {}).get("name") == _TOOL_NAME),
                None,
            )
            if call is None:
                raise RuntimeError(f"no tool_calls in openai-compat response: {data}")
            raw_json = json.loads(call["function"]["arguments"])
            usage = data.get("usage", {})
            return ProviderResult(
                raw_json=raw_json,
                model_id=data.get("model", model_id),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
