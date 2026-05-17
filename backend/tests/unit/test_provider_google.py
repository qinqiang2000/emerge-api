"""Test Google Gemini adapter via mock genai.Client."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.provider.base import DocumentBlock, TextBlock


_SCHEMA = {"type": "object", "properties": {"entities": {"type": "array"}}, "required": ["entities"]}


def _mock_response(payload: dict, in_tokens: int = 100, out_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.text = json.dumps(payload)
    resp.usage_metadata = MagicMock(prompt_token_count=in_tokens, candidates_token_count=out_tokens)
    return resp


async def test_google_extract_happy_path() -> None:
    from app.provider.google import GoogleProvider

    payload = {"entities": [{"invoice_no": "INV-1"}]}

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        client.aio.models.generate_content = AsyncMock(return_value=_mock_response(payload))

        p = GoogleProvider(api_key="g-test")
        result = await p.extract(
            model_id="gemini-2.5-flash",
            system_prompt="extract",
            user_content=[TextBlock(text="hi"), DocumentBlock(media_type="application/pdf", data_b64="JVBERi0=")],
            response_schema=_SCHEMA,
        )
    assert result.raw_json == payload
    assert result.model_id == "gemini-2.5-flash"
    assert result.input_tokens == 100
    assert result.output_tokens == 50


async def test_google_retries_on_rate_limit() -> None:
    from app.provider.google import GoogleProvider

    payload = {"entities": []}

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        client.aio.models.generate_content = AsyncMock(
            side_effect=[
                Exception("rate limit hit (429)"),
                _mock_response(payload),
            ]
        )

        p = GoogleProvider(api_key="g-test", retry_base_delay=0.0)
        result = await p.extract(
            model_id="gemini-2.5-flash",
            system_prompt="x",
            user_content=[TextBlock(text="x")],
            response_schema=_SCHEMA,
        )
    assert result.raw_json == payload


async def test_google_does_not_retry_non_retryable() -> None:
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        client.aio.models.generate_content = AsyncMock(side_effect=ValueError("hard fail"))

        p = GoogleProvider(api_key="g-test", retry_base_delay=0.0)
        with pytest.raises(ValueError):
            await p.extract(
                model_id="gemini-2.5-flash",
                system_prompt="x",
                user_content=[TextBlock(text="x")],
                response_schema=_SCHEMA,
            )
