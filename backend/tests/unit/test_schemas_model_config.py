from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.model_config import ModelConfig, infer_provider_from_model_id


def test_minimal_model_config() -> None:
    mc = ModelConfig(
        model_id="m_default",
        label="Default",
        provider="google",
        provider_model_id="gemini-2.5-flash",
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert mc.params == {}


def test_with_params() -> None:
    mc = ModelConfig(
        model_id="m_sonnet",
        label="Claude Sonnet",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
        params={"temperature": 0.0, "max_tokens": 4096},
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert mc.params["temperature"] == 0.0


def test_codex_provider_config() -> None:
    mc = ModelConfig(
        model_id="m_codex_gpt55_fast",
        label="Codex GPT-5.5 Fast",
        provider="codex",
        provider_model_id="gpt-5.5",
        params={"temperature": 0.0, "fast": True, "reasoning_effort": "high"},
        created_at="2026-05-12T00:00:00+00:00",
    )
    assert mc.provider == "codex"


def test_provider_literal_constraint() -> None:
    with pytest.raises(ValidationError):
        ModelConfig(
            model_id="m_x",
            label="x",
            provider="azure",  # type: ignore[arg-type]
            provider_model_id="x",
            created_at="2026-05-12T00:00:00+00:00",
        )


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("claude-sonnet-4-6", "anthropic"),
        ("claude-opus-4-7", "anthropic"),
        ("gpt-4o-2024-08", "openai"),
        ("o1-preview", "openai"),
        ("o3-mini", "openai"),
        ("gemini-2.5-flash", "google"),
        ("gemini-2.5-pro", "google"),
        ("gemma-4-12b-it", "google"),
        ("totally-unknown-model", "google"),  # fallback
    ],
)
def test_infer_provider_from_model_id(model_id: str, expected: str) -> None:
    assert infer_provider_from_model_id(model_id) == expected
