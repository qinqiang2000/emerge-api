import json

import httpx
import pytest
import respx

from app.provider.base import DocumentBlock, TextBlock
from app.provider.codex import CodexCliProvider


SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {"type": "array"},
    },
    "required": ["entities"],
}


def _write_codex_auth(tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text(
        json.dumps({
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": "access-test",
                "refresh_token": "refresh-test",
            },
        }),
        encoding="utf-8",
    )
    return codex_home


def _response(payload: dict) -> dict:
    return {
        "id": "resp_1",
        "model": "gpt-5.5",
        "output": [
            {
                "type": "function_call",
                "name": "emit_extraction",
                "arguments": json.dumps(payload),
            }
        ],
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }


def _sse_response(payload: dict) -> str:
    done = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "name": "emit_extraction",
            "arguments": json.dumps(payload),
        },
    }
    completed = {
        "type": "response.completed",
        "response": {
            "model": "gpt-5.5",
            "usage": {"input_tokens": 7, "output_tokens": 3},
        },
    }
    return (
        f"data: {json.dumps(done)}\n\n"
        f"data: {json.dumps(completed)}\n\n"
        "data: [DONE]\n\n"
    )


@pytest.mark.respx(base_url="https://chatgpt.com")
async def test_codex_provider_uses_codex_cli_token_and_fast_params(
    respx_mock: respx.MockRouter,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(_write_codex_auth(tmp_path)))
    payload = {"entities": [{"invoice_no": "INV-1"}]}
    route = respx_mock.post("/backend-api/codex/responses").mock(
        return_value=httpx.Response(200, text=_sse_response(payload))
    )

    provider = CodexCliProvider()
    result = await provider.extract(
        model_id="gpt-5.5",
        system_prompt="extract",
        user_content=[TextBlock(text="fields")],
        response_schema=SCHEMA,
        params={"temperature": 0.0, "fast": True, "reasoning_effort": "high"},
    )

    assert result.raw_json == payload
    assert result.model_id == "gpt-5.5"
    assert result.input_tokens == 7
    assert result.output_tokens == 3
    body = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["authorization"] == "Bearer access-test"
    assert body["model"] == "gpt-5.5"
    assert body["service_tier"] == "priority"
    assert body["reasoning"]["effort"] == "high"
    assert body["tool_choice"] == {"type": "function", "name": "emit_extraction"}


@pytest.mark.respx(base_url="https://chatgpt.com")
async def test_codex_provider_includes_pdf_as_input_file(
    respx_mock: respx.MockRouter,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(_write_codex_auth(tmp_path)))
    route = respx_mock.post("/backend-api/codex/responses").mock(
        return_value=httpx.Response(200, text=_sse_response({"entities": []}))
    )
    provider = CodexCliProvider()
    await provider.extract(
        model_id="gpt-5.5",
        system_prompt="extract",
        user_content=[
            TextBlock(text="fields"),
            DocumentBlock(media_type="application/pdf", data_b64="JVBERi0xLjQ="),
        ],
        response_schema=SCHEMA,
    )

    body = json.loads(route.calls[0].request.content)
    parts = body["input"][0]["content"]
    assert any(p.get("type") == "input_file" for p in parts)
