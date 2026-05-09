import json

import httpx
import pytest
import respx

from app.provider.anthropic import AnthropicProvider
from app.provider.base import TextBlock, DocumentBlock
from app.provider.retry import RetryableError


SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array"},
    },
    "required": ["entities"],
}


def _tool_use_response(payload: dict) -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "emit_extraction",
                "input": payload,
            },
        ],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_happy_path(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": [{"invoice_no": "INV-1"}]}
    respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(200, json=_tool_use_response(payload))
    )

    p = AnthropicProvider(api_key="sk-test")
    result = await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="you are an extractor",
        user_content=[TextBlock(text="hi")],
        response_schema=SCHEMA,
    )
    assert result.raw_json == payload
    assert result.model_id == "claude-sonnet-4-6"
    assert result.input_tokens == 100
    assert result.output_tokens == 50


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_retries_on_429(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": []}
    respx_mock.post("/v1/messages").mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "rate"}}),
            httpx.Response(200, json=_tool_use_response(payload)),
        ]
    )

    p = AnthropicProvider(api_key="sk-test", retry_base_delay=0.0)
    result = await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="x",
        user_content=[TextBlock(text="x")],
        response_schema=SCHEMA,
    )
    assert result.raw_json == payload


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_gives_up_after_retries(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate"}})
    )
    p = AnthropicProvider(api_key="sk-test", retry_base_delay=0.0, retry_max_attempts=2)
    with pytest.raises(RetryableError):
        await p.extract(
            model_id="claude-sonnet-4-6",
            system_prompt="x",
            user_content=[TextBlock(text="x")],
            response_schema=SCHEMA,
        )


@pytest.mark.respx(base_url="https://api.anthropic.com")
async def test_extract_includes_document_block(respx_mock: respx.MockRouter) -> None:
    payload = {"entities": []}
    route = respx_mock.post("/v1/messages").mock(
        return_value=httpx.Response(200, json=_tool_use_response(payload))
    )
    p = AnthropicProvider(api_key="sk-test")
    await p.extract(
        model_id="claude-sonnet-4-6",
        system_prompt="x",
        user_content=[
            TextBlock(text="extract this"),
            DocumentBlock(media_type="application/pdf", data_b64="JVBERi0xLjQ="),
        ],
        response_schema=SCHEMA,
    )
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "claude-sonnet-4-6"
    user_blocks = body["messages"][0]["content"]
    assert any(b.get("type") == "document" for b in user_blocks)
