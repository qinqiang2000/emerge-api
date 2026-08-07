"""Amazon Bedrock `bedrock-mantle` endpoint — OpenAI **Responses** API.

Why a separate adapter instead of reusing `app.provider.openai`:

* Mantle's GPT-5.x models are Responses-only. Their model cards mark
  "Chat Completions" as NOT supported, so `openai.py` (which posts to
  `/chat/completions`) 404s/400s against them.
* The wire shapes differ. Responses uses a flat function-tool
  (``{"type":"function","name":…,"parameters":…}``) where Chat Completions
  nests it under ``function``; the reply arrives as an ``output`` array of
  typed items (``reasoning`` / ``function_call`` / ``message``) rather than
  ``choices[0].message.tool_calls``.
* PDFs work here. `openai.py` sets ``supports_pdf = False`` because the
  OpenAI-compatible ``image_url`` block rejects raw PDF bytes; Responses has a
  first-class ``input_file`` block that Mantle parses server-side, so callers
  need not rasterize upstream.

Path gotcha: GPT-5.x lives under ``/openai/v1`` on the mantle host, NOT the
``/v1`` the other mantle models use. Posting a GPT-5.x request to ``/v1/responses``
returns a very explicit 400 ("does not support the '/v1/responses' API"), so the
default base URL below encodes the ``/openai/v1`` form.

``strict`` is deliberately left OFF on the emitted function tool. The project's
`_build_response_schema` produces OpenAPI-3.0-flavoured JSON (``nullable: true``
rather than union types) and omits ``additionalProperties``; OpenAI strict mode
rejects that outright with ``invalid_function_parameters`` ("'additionalProperties'
is required to be supplied and to be false"). Forced ``tool_choice`` already
guarantees the call is emitted, and downstream pydantic validates the payload.
"""
from __future__ import annotations

import json
import os
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


_TOOL_NAME = "emit_extraction"
_DEFAULT_REGION = "us-east-1"


def _default_base_url(region: str) -> str:
    return f"https://bedrock-mantle.{region}.api.aws/openai/v1"


def _responses_url(base_url: str | None, region: str) -> str:
    """Resolve the /responses endpoint. Tolerates a base_url given as host-root,
    `…/openai/v1`, or a full `…/responses` (mirrors `openai._chat_completions_url`)."""
    b = (base_url or _default_base_url(region)).rstrip("/")
    if b.endswith("/responses"):
        return b
    return b + "/responses"


def _block_to_mantle(b: ContentBlock) -> dict[str, Any]:
    if isinstance(b, TextBlock):
        return {"type": "input_text", "text": b.text}
    if isinstance(b, ImageBlock):
        return {
            "type": "input_image",
            "image_url": f"data:{b.media_type};base64,{b.data_b64}",
        }
    if isinstance(b, DocumentBlock):
        # Mantle parses the PDF server-side; `filename` is required by the API
        # but only surfaces in the model's view of the attachment.
        return {
            "type": "input_file",
            "filename": "document.pdf",
            "file_data": f"data:{b.media_type};base64,{b.data_b64}",
        }
    raise ValueError(f"unknown block type: {b!r}")


class BedrockMantleProvider(Provider):
    # Verified against openai.gpt-5.6-terra: a 198KB invoice PDF sent as an
    # `input_file` block is read natively (correct invoice no. / total / tax).
    supports_pdf = True

    def __init__(
        self,
        *,
        api_key: str,
        proxy: str | None = None,
        base_url: str | None = None,
        region: str | None = None,
        timeout: float = 300.0,
        retry_max_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._api_key = api_key
        self._proxy = proxy
        self._region = region or os.getenv("AWS_REGION") or _DEFAULT_REGION
        self._url = _responses_url(base_url, self._region)
        # Reasoning models are slow to first byte: at the API-default effort a
        # trivial prompt has been observed to exceed 120s. Default generously.
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
        body: dict[str, Any] = {
            "model": model_id,
            "input": [
                {
                    "role": "user",
                    "content": [_block_to_mantle(b) for b in user_content],
                }
            ],
            "tools": [
                {
                    "type": "function",
                    "name": _TOOL_NAME,
                    "description": "Emit the structured extraction result.",
                    "parameters": response_schema,
                }
            ],
            "tool_choice": {"type": "function", "name": _TOOL_NAME},
            # Responses defaults `store` to true, which retains the full request
            # AND response (i.e. customer documents) for 30 days in-region. This
            # adapter is stateless — it never uses `previous_response_id` — so
            # opt out on every call rather than leaving documents server-side.
            "store": False,
        }
        if system_prompt:
            # Responses' first-class system channel. Kept out of `input` so the
            # user turn stays purely the document + instruction blocks.
            body["instructions"] = system_prompt
        if params.get("effort"):
            body["reasoning"] = {"effort": params["effort"]}
        if params.get("max_tokens"):
            body["max_output_tokens"] = params["max_tokens"]
        # `temperature` is deliberately NOT forwarded: GPT-5.x reasoning models
        # reject a non-default value, and every existing ModelConfig in this repo
        # carries `temperature: 0.0` from the Gemini/Anthropic defaults. Silently
        # dropping it keeps those configs reusable verbatim.

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
                        raise RetryableError(
                            f"bedrock-mantle {resp.status_code}: {resp.text[:200]}"
                        )
                    resp.raise_for_status()
                    data = resp.json()
            except RetryableError:
                raise
            except Exception as e:  # noqa: BLE001
                if is_transient(e):
                    raise RetryableError(str(e) or type(e).__name__) from e
                raise

            # `output` interleaves typed items; the tool call is one of them and
            # is preceded by an opaque `reasoning` item on GPT-5.x.
            call = next(
                (
                    it
                    for it in data.get("output", [])
                    if it.get("type") == "function_call" and it.get("name") == _TOOL_NAME
                ),
                None,
            )
            if call is None:
                raise RuntimeError(
                    f"no {_TOOL_NAME} function_call in mantle response: "
                    f"{json.dumps(data)[:500]}"
                )
            raw_json = json.loads(call["arguments"])
            usage = data.get("usage", {})
            return ProviderResult(
                raw_json=raw_json,
                model_id=data.get("model", model_id),
                # Responses names these input_/output_tokens (Chat Completions
                # uses prompt_/completion_tokens).
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            )

        return await retry_async(
            _call,
            max_attempts=self._retry_max,
            base_delay=self._retry_base,
        )
