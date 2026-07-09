"""Factory tests for per-model endpoint (deepseek-style anthropic-compatible gateway).

Red lines under test:
  • per-model base_url/api_key_env resolve onto the AnthropicProvider.
  • absent → fall back to global ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY (existing
    claude models unchanged).
  • the factory only READS env; enabling a deepseek model never mutates
    os.environ["ANTHROPIC_BASE_URL"] (Agent brain ↔ Extract LLM separation).
"""
from __future__ import annotations

import os

from app.provider import get_provider_for_model
from app.provider.anthropic import AnthropicProvider


def test_per_model_base_url_and_key_env(monkeypatch) -> None:
    monkeypatch.setenv("SOME_TEST_ENV", "sk-deepseek-test-value")
    # A global gateway is also set to prove per-model wins over it.
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://global.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-global")

    prov = get_provider_for_model(
        "deepseek-v4-flash",
        provider="anthropic",
        base_url="https://api.deepseek.com/anthropic",
        api_key_env="SOME_TEST_ENV",
    )
    assert isinstance(prov, AnthropicProvider)
    assert "api.deepseek.com" in prov._url
    assert prov._url.endswith("/v1/messages")
    assert prov._api_key == "sk-deepseek-test-value"
    # A custom per-model gateway disables thinking so forced tool_choice works
    # (deepseek-v4-* 400s otherwise). See AnthropicProvider._disable_thinking.
    assert prov._disable_thinking is True


def test_claude_global_gateway_keeps_thinking_default(monkeypatch) -> None:
    """The global ANTHROPIC_BASE_URL (claude) is NOT a custom per-model gateway,
    so thinking is left at the API default (field omitted) — no regression."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-global-claude")
    prov = get_provider_for_model("claude-sonnet-4-6", provider="anthropic")
    assert isinstance(prov, AnthropicProvider)
    assert prov._disable_thinking is False


def test_fallback_to_global_env_for_claude(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-global-claude")

    prov = get_provider_for_model("claude-sonnet-4-6", provider="anthropic")
    assert isinstance(prov, AnthropicProvider)
    assert "gateway.example" in prov._url
    assert prov._api_key == "sk-global-claude"


def test_fallback_via_model_id_prefix(monkeypatch) -> None:
    """The startswith('claude') prefix branch (provider not passed) also falls back."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-prefix")

    prov = get_provider_for_model("claude-opus-4-8")
    assert isinstance(prov, AnthropicProvider)
    assert "gw.example" in prov._url
    assert prov._api_key == "sk-prefix"


def test_prefix_branch_honors_per_model_endpoint(monkeypatch) -> None:
    """A deepseek-* model routed via the prefix branch still takes per-model base_url."""
    monkeypatch.setenv("DEEPSEEK_KEY_TEST", "sk-ds-prefix")
    prov = get_provider_for_model(
        "claude-compat-deepseek",  # forces the startswith('claude') branch
        base_url="https://api.deepseek.com/anthropic",
        api_key_env="DEEPSEEK_KEY_TEST",
    )
    assert isinstance(prov, AnthropicProvider)
    assert "api.deepseek.com" in prov._url
    assert prov._api_key == "sk-ds-prefix"


def test_factory_never_writes_environ(monkeypatch) -> None:
    """Agent-brain purity: building a deepseek extractor must not mutate the
    global ANTHROPIC_BASE_URL the Claude SDK relies on."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://agent-brain-gateway/anthropic")
    monkeypatch.setenv("DS_KEY_TEST", "sk-ds")

    get_provider_for_model(
        "deepseek-v4-flash",
        provider="anthropic",
        base_url="https://api.deepseek.com/anthropic",
        api_key_env="DS_KEY_TEST",
    )
    assert os.environ.get("ANTHROPIC_BASE_URL") == "https://agent-brain-gateway/anthropic"


def test_openai_compat_gateway_resolves_and_disables_thinking(monkeypatch) -> None:
    """DashScope/Qwen: `provider=openai` + per-model base_url → OpenAIProvider on
    the gateway's /chat/completions, thinking disabled so forced tool_choice is
    accepted (the gateway 400s otherwise)."""
    from app.provider.openai import OpenAIProvider

    monkeypatch.setenv("DASHSCOPE_KEY_TEST", "sk-dashscope")
    prov = get_provider_for_model(
        "qwen3.7-plus",
        provider="openai",
        base_url="https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_KEY_TEST",
    )
    assert isinstance(prov, OpenAIProvider)
    assert prov._url.endswith("/compatible-mode/v1/chat/completions")
    assert prov._api_key == "sk-dashscope"
    assert prov._disable_thinking is True


def test_openai_provider_cannot_read_pdf_natively() -> None:
    """Capability lives on the adapter, not on ModelConfig: `image_url` rejects
    raw PDF bytes, so callers must rasterize. Anthropic/Google rasterize PDF
    server-side and keep the default."""
    from app.provider.anthropic import AnthropicProvider
    from app.provider.openai import OpenAIProvider

    assert OpenAIProvider.supports_pdf is False
    assert AnthropicProvider.supports_pdf is True


def test_missing_api_key_env_resolves_empty(monkeypatch) -> None:
    """api_key_env pointing at an unset var resolves to None (not a crash); the
    provider is still constructed so the failure surfaces at call time, not build."""
    monkeypatch.delenv("NO_SUCH_KEY_ENV", raising=False)
    prov = get_provider_for_model(
        "deepseek-v4-flash",
        provider="anthropic",
        base_url="https://api.deepseek.com/anthropic",
        api_key_env="NO_SUCH_KEY_ENV",
    )
    assert isinstance(prov, AnthropicProvider)
    assert prov._api_key is None
