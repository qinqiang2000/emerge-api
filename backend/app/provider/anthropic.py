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
from app.provider.retry import RetryableError, is_transient, retry_async


_API_URL = "https://api.anthropic.com/v1/messages"
_TOOL_NAME = "emit_extraction"


def _messages_url(base_url: str | None) -> str:
    """Resolve the /v1/messages endpoint.

    Hard rule (MEMORY:feedback_anthropic_no_direct_api): Anthropic traffic must
    route through the configured `ANTHROPIC_BASE_URL` gateway, never
    api.anthropic.com directly. When a base_url is set we point at it; the
    default constant is kept only as the no-gateway fallback. Tolerates a
    base_url given as host-root, `…/v1`, or a full `…/v1/messages`.
    """
    if not base_url:
        return _API_URL
    b = base_url.rstrip("/")
    if b.endswith("/messages"):
        return b
    if b.endswith("/v1"):
        return b + "/messages"
    return b + "/v1/messages"


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
        base_url: str | None = None,
        timeout: float = 120.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
        disable_thinking: bool = False,
    ) -> None:
        self._api_key = api_key
        self._proxy = proxy
        self._url = _messages_url(base_url)
        self._timeout = timeout
        self._retry_max = retry_max_attempts
        self._retry_base = retry_base_delay
        # Some anthropic-compatible third-party gateways (e.g. deepseek-v4-*)
        # default to a "thinking" mode that REJECTS forced tool_choice with a
        # 400 ("Thinking mode does not support this tool_choice"). We rely on
        # forced tool_choice for structured extraction, so disable thinking on
        # those gateways. Sent only when explicitly requested (custom gateway);
        # the real Anthropic endpoint omits the field entirely (its default is
        # already no extended thinking), so claude models are unaffected.
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
        body: dict[str, Any] = {
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
        thinking = params.get("thinking")
        if thinking:
            # Per-model opt-in（模型配置 params.thinking, anthropic 格式
            # {"type": "enabled"}）。思考模式与强制 tool_choice 互斥（网关 400），
            # 降为 auto，靠 system prompt 约束模型仍调用抽取工具；思考 token 计入
            # max_tokens，调用方应给足预算。effort 经 params.output_config 透传
            # （{"effort": "high/max"}，网关默认 high）。温度在思考模式下移除——
            # 部分 anthropic 兼容网关会拒绝它。
            body["thinking"] = thinking
            body["tool_choice"] = {"type": "auto"}
            body.pop("temperature", None)
            if params.get("output_config"):
                body["output_config"] = params["output_config"]
        elif self._disable_thinking:
            # Gateway-specific: opt out of extended/thinking mode so forced
            # tool_choice is accepted. Harmless on gateways that ignore it.
            body["thinking"] = {"type": "disabled"}
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
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
                        raise RetryableError(f"anthropic {resp.status_code}: {resp.text[:200]}")
                    resp.raise_for_status()
                    data = resp.json()
            except RetryableError:
                raise
            except Exception as e:  # noqa: BLE001
                # Transport-layer blip (ConnectError / ReadError / proxy
                # disconnect) carries an empty/opaque message — classify by
                # type so it retries instead of failing on the first shot.
                if is_transient(e):
                    raise RetryableError(str(e) or type(e).__name__) from e
                raise
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
