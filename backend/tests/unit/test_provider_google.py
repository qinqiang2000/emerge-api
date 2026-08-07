"""Test Google Gemini adapter via mock genai.Client."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.provider.base import DocumentBlock, TextBlock


_SCHEMA = {"type": "object", "properties": {"entities": {"type": "array"}}, "required": ["entities"]}


def _mock_response(payload: dict, in_tokens: int = 100, out_tokens: int = 50) -> MagicMock:
    resp = MagicMock()
    resp.text = json.dumps(payload)
    # thoughts_token_count MUST be pinned explicitly: on a bare MagicMock the
    # attribute auto-vivifies, and pydantic coerces that child Mock through
    # __int__ into a bogus `1` instead of failing — a silently wrong token
    # count. See tests/unit/test_provider_google_thinking_tokens.py.
    resp.usage_metadata = MagicMock(
        prompt_token_count=in_tokens,
        candidates_token_count=out_tokens,
        thoughts_token_count=0,
    )
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


# ── Thinking control: thinking_budget (2.5) vs thinking_level (3.x) ──────────


async def _sent_config(params: dict | None):
    """Run extract() against a mocked client; return the GenerateContentConfig."""
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        gen = AsyncMock(return_value=_mock_response({"entities": []}))
        client.aio.models.generate_content = gen

        p = GoogleProvider(api_key="g-test", retry_base_delay=0.0)
        await p.extract(
            model_id="gemini-3-flash-preview",
            system_prompt="x",
            user_content=[TextBlock(text="x")],
            response_schema=_SCHEMA,
            params=params,
        )
        return gen.call_args.kwargs["config"]


async def _extract_raises(params: dict):
    """Run extract() expecting a config-time ValueError; assert no API call."""
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        client = mock_client_cls.return_value
        gen = AsyncMock(return_value=_mock_response({"entities": []}))
        client.aio.models.generate_content = gen

        p = GoogleProvider(api_key="g-test", retry_base_delay=0.0)
        with pytest.raises(ValueError) as ei:
            await p.extract(
                model_id="gemini-3-flash-preview",
                system_prompt="x",
                user_content=[TextBlock(text="x")],
                response_schema=_SCHEMA,
                params=params,
            )
        # A bad params dict must never cost a round trip (or a retry storm).
        gen.assert_not_awaited()
        return str(ei.value)


@pytest.mark.parametrize("params", [None, {}, {"temperature": 0.2}])
async def test_no_thinking_params_sends_no_thinking_config(params) -> None:
    """Regression guard: every existing ModelConfig omits both knobs, and must
    keep reaching the API with `thinking_config` entirely unset — not merely
    None — so the model's own default thinking stays in force."""
    cfg = await _sent_config(params)
    assert "thinking_config" not in cfg.model_fields_set
    assert cfg.thinking_config is None


@pytest.mark.parametrize("level", ["low", "high", "HIGH", "Medium", "minimal"])
async def test_thinking_level_forwarded_case_insensitively(level) -> None:
    from google.genai import types

    cfg = await _sent_config({"thinking_level": level})
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel(level.upper())
    # The 2.5 knob must not be back-filled alongside it.
    assert cfg.thinking_config.thinking_budget is None


@pytest.mark.parametrize("budget", [0, 512, -1])
async def test_thinking_budget_unchanged(budget) -> None:
    """`thinking_budget=0` is the OCR path's reasoning-off switch — it is a
    real value, not a falsy 'unset', and must survive."""
    cfg = await _sent_config({"thinking_budget": budget})
    assert cfg.thinking_config.thinking_budget == budget
    assert cfg.thinking_config.thinking_level is None


async def test_both_thinking_knobs_rejected() -> None:
    """Neither wins: one ModelConfig pins one model generation, so both set at
    once is a config bug that must be loud rather than half-honoured."""
    msg = await _extract_raises({"thinking_budget": 0, "thinking_level": "low"})
    assert "thinking_budget" in msg and "thinking_level" in msg


async def test_invalid_thinking_level_rejected() -> None:
    """The SDK enum only warns on unknown strings and forwards them, so without
    our check this would surface as an opaque 400 mid-extraction."""
    msg = await _extract_raises({"thinking_level": "turbo"})
    assert "turbo" in msg
    assert "HIGH" in msg and "LOW" in msg


async def test_non_string_thinking_level_rejected() -> None:
    msg = await _extract_raises({"thinking_level": 512})
    assert "512" in msg


# ── Client construction: which Gemini surface for which args ─────────────────


def test_google_aistudio_default_branch() -> None:
    """No vertex flag → plain AI Studio api_key client, never vertexai."""
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        GoogleProvider(api_key="ai-studio-key")
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["api_key"] == "ai-studio-key"
        assert "vertexai" not in kwargs


def test_google_vertex_apikey_express_branch() -> None:
    """use_vertex + api_key → express mode: vertexai+api_key, NO project/location.

    project/location are mutually exclusive with api_key in the SDK (it raises if
    both are passed), and the key wins on conflict — so they must be dropped here.
    """
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        GoogleProvider(
            api_key="AQ.vertex-key",
            use_vertex=True,
            vertex_project="proj-x",
            vertex_location="us-east4",
        )
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["api_key"] == "AQ.vertex-key"
        assert "project" not in kwargs
        assert "location" not in kwargs


def test_google_vertex_adc_branch_when_no_key() -> None:
    """use_vertex + empty api_key → ADC: vertexai+project+location, no api_key."""
    from app.provider.google import GoogleProvider

    with patch("google.genai.Client") as mock_client_cls:
        GoogleProvider(
            api_key="",
            use_vertex=True,
            vertex_project="proj-x",
            vertex_location="us-central1",
        )
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["project"] == "proj-x"
        assert kwargs["location"] == "us-central1"
        assert "api_key" not in kwargs


# ── Factory routing from env vars ────────────────────────────────────────────


def test_factory_enterprise_alias_and_dedicated_key(monkeypatch) -> None:
    """GOOGLE_GENAI_USE_ENTERPRISE flips Vertex; GOOGLE_VERTEX_API_KEY preferred,
    and a present AI Studio GOOGLE_API_KEY is left untouched (key wins)."""
    from app.provider import get_provider_for_model

    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "true")
    monkeypatch.setenv("GOOGLE_VERTEX_API_KEY", "AQ.vertex-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "ai-studio-key")
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    with patch("google.genai.Client") as mock_client_cls:
        get_provider_for_model("gemini-2.5-flash")
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["api_key"] == "AQ.vertex-key"


def test_factory_vertex_key_falls_back_to_google_api_key(monkeypatch) -> None:
    """Doc-literal config: GOOGLE_API_KEY holds the Vertex key, no dedicated var."""
    from app.provider import get_provider_for_model

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "1")
    monkeypatch.delenv("GOOGLE_VERTEX_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_ENTERPRISE", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "AQ.in-google-api-key")

    with patch("google.genai.Client") as mock_client_cls:
        get_provider_for_model("gemini-2.5-flash")
        kwargs = mock_client_cls.call_args.kwargs
        assert kwargs["vertexai"] is True
        assert kwargs["api_key"] == "AQ.in-google-api-key"
