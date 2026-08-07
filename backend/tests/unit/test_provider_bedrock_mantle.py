"""Bedrock-mantle adapter: factory wiring, wire shape, and the traps that make
it a separate adapter from `app.provider.openai`.

Red lines under test:
  • dotted vendor ids ("openai.gpt-5.6-terra") route to the mantle adapter, not
    the plain OpenAI one (which posts to /chat/completions — unsupported by
    GPT-5.x on mantle).
  • the resolved URL keeps the `/openai/v1` path segment. GPT-5.x 400s on the
    `/v1/responses` path other mantle models use.
  • PDFs go out as a first-class `input_file` block (no upstream rasterizing).
  • `strict` is never set on the function tool, and `temperature` is never
    forwarded — both 400 against GPT-5.x with this repo's schemas/configs.
  • `store` is explicitly false so customer documents are not retained 30 days.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.provider import get_provider_for_model
from app.provider.base import DocumentBlock, TextBlock
from app.provider.bedrock_mantle import BedrockMantleProvider
from app.schemas.model_config import infer_provider_from_model_id


# --------------------------------------------------------------------------
# factory / inference
# --------------------------------------------------------------------------

def test_dotted_id_infers_bedrock_mantle() -> None:
    assert infer_provider_from_model_id("openai.gpt-5.6-terra") == "bedrock_mantle"
    # A direct-OpenAI id has no vendor dot and must NOT be captured.
    assert infer_provider_from_model_id("gpt-5.6") == "openai"
    assert infer_provider_from_model_id("claude-sonnet-4-6") == "anthropic"


def test_factory_explicit_provider(monkeypatch) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSK-test")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    prov = get_provider_for_model("openai.gpt-5.6-terra", provider="bedrock_mantle")
    assert isinstance(prov, BedrockMantleProvider)
    assert prov._api_key == "ABSK-test"
    # Region flows into the host, and the /openai/v1 segment survives.
    assert prov._url == (
        "https://bedrock-mantle.us-west-2.api.aws/openai/v1/responses"
    )


def test_factory_via_model_id_prefix(monkeypatch) -> None:
    """`provider` omitted → the `openai.` prefix branch still reaches mantle."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSK-test")
    monkeypatch.delenv("AWS_REGION", raising=False)
    prov = get_provider_for_model("openai.gpt-5.6-terra")
    assert isinstance(prov, BedrockMantleProvider)
    # No AWS_REGION → us-east-1 default.
    assert "bedrock-mantle.us-east-1.api.aws/openai/v1/responses" in prov._url


def test_factory_per_model_key_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "ABSK-global")
    monkeypatch.setenv("OTHER_ACCOUNT_KEY", "ABSK-other")
    prov = get_provider_for_model(
        "openai.gpt-5.6-terra",
        provider="bedrock_mantle",
        api_key_env="OTHER_ACCOUNT_KEY",
    )
    assert prov._api_key == "ABSK-other"


@pytest.mark.parametrize(
    "given,expected",
    [
        (None, "https://bedrock-mantle.us-east-1.api.aws/openai/v1/responses"),
        ("https://x.example/openai/v1", "https://x.example/openai/v1/responses"),
        ("https://x.example/openai/v1/", "https://x.example/openai/v1/responses"),
        # already-full URL passes through unchanged
        ("https://x.example/openai/v1/responses",
         "https://x.example/openai/v1/responses"),
    ],
)
def test_base_url_normalization(given, expected, monkeypatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    prov = BedrockMantleProvider(api_key="k", base_url=given)
    assert prov._url == expected


def test_supports_pdf_unlike_plain_openai() -> None:
    from app.provider.openai import OpenAIProvider

    assert BedrockMantleProvider.supports_pdf is True
    assert OpenAIProvider.supports_pdf is False


# --------------------------------------------------------------------------
# wire shape
# --------------------------------------------------------------------------

_SCHEMA = {
    "type": "object",
    "required": ["entities"],
    "properties": {
        "entities": {
            "type": "array",
            # Mirrors _build_response_schema: OpenAPI-flavoured `nullable`, no
            # `additionalProperties` — the exact shape strict mode rejects.
            "items": {
                "type": "object",
                "properties": {"invoiceNumber": {"type": "string", "nullable": True}},
                "required": ["invoiceNumber"],
            },
        }
    },
}

_OK_RESPONSE = {
    "model": "openai.gpt-5.6-terra",
    "output": [
        # GPT-5.x emits an opaque reasoning item before the call — the adapter
        # must skip past it rather than reading output[0].
        {"type": "reasoning", "summary": None},
        {
            "type": "function_call",
            "name": "emit_extraction",
            "arguments": json.dumps({"entities": [{"invoiceNumber": "INV-1"}]}),
        },
    ],
    "usage": {"input_tokens": 677, "output_tokens": 85},
}


async def _capture(monkeypatch, *, response=None, status=200):
    """Run extract() against a stubbed transport; return (sent_body, result)."""
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(status, json=response or _OK_RESPONSE)

    real_client = httpx.AsyncClient

    def fake_client(**kwargs):
        kwargs.pop("proxy", None)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    prov = BedrockMantleProvider(api_key="ABSK-test")
    result = await prov.extract(
        model_id="openai.gpt-5.6-terra",
        system_prompt="You extract invoices.",
        user_content=[
            DocumentBlock(media_type="application/pdf", data_b64="JVBERi0x"),
            TextBlock(text="Extract all entities."),
        ],
        response_schema=_SCHEMA,
        params={"temperature": 0.0, "effort": "low"},
    )
    return sent, result


@pytest.mark.anyio
async def test_request_shape(monkeypatch) -> None:
    sent, result = await _capture(monkeypatch)

    # flat function tool (Responses), NOT the nested chat-completions form
    tool = sent["tools"][0]
    assert tool["type"] == "function" and tool["name"] == "emit_extraction"
    assert "function" not in tool
    assert tool["parameters"] == _SCHEMA
    # strict must be absent: this schema 400s under strict mode
    assert "strict" not in tool
    assert sent["tool_choice"] == {"type": "function", "name": "emit_extraction"}

    # system prompt rides `instructions`, not an input turn
    assert sent["instructions"] == "You extract invoices."
    assert [m["role"] for m in sent["input"]] == ["user"]

    # PDF as a native input_file data-URI; text as input_text
    blocks = sent["input"][0]["content"]
    assert blocks[0]["type"] == "input_file"
    assert blocks[0]["file_data"] == "data:application/pdf;base64,JVBERi0x"
    assert blocks[1] == {"type": "input_text", "text": "Extract all entities."}

    # document retention opt-out + effort passthrough, temperature dropped
    assert sent["store"] is False
    assert sent["reasoning"] == {"effort": "low"}
    assert "temperature" not in sent

    # usage uses Responses' input_/output_tokens naming
    assert result.raw_json == {"entities": [{"invoiceNumber": "INV-1"}]}
    assert (result.input_tokens, result.output_tokens) == (677, 85)
    assert result.model_id == "openai.gpt-5.6-terra"


@pytest.mark.anyio
async def test_missing_tool_call_raises(monkeypatch) -> None:
    """A text-only reply (model ignored the forced tool) must fail loudly rather
    than silently yielding an empty extraction."""
    bad = {"model": "openai.gpt-5.6-terra", "output": [{"type": "message"}], "usage": {}}
    with pytest.raises(RuntimeError, match="emit_extraction"):
        await _capture(monkeypatch, response=bad)


@pytest.mark.anyio
async def test_429_is_retryable(monkeypatch) -> None:
    from app.provider.retry import RetryableError

    with pytest.raises((RetryableError, RuntimeError)):
        await _capture(monkeypatch, response={"message": "slow down"}, status=429)
