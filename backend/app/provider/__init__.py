"""Provider factory: pick an adapter by model_id prefix.

Each adapter defaults to NO proxy (trust_env=False internally) to avoid leaking the
agent-side `CLAUDE_PROXY` (a SOCKS5 tunnel meant for the Claude SDK) into HTTP API
calls. To set a proxy for a given extractor, define `GOOGLE_PROXY` (for Gemini) or
`ANTHROPIC_PROXY` (for Anthropic-as-extractor) in the env. They follow the same
http(s):// or socks5:// schemes httpx accepts.
"""
import os
from typing import Optional

from app.provider.base import Provider
from app.schemas.model_config import Provider as ModelProvider


def get_provider_for_model(
    model_id: str,
    *,
    provider: ModelProvider | None = None,
    api_key: Optional[str] = None,
) -> Provider:
    """Returns an extractor Provider for the given model_id.

    Reads API keys and proxy URLs from environment unless explicitly passed.
    """
    if provider == "codex":
        from app.provider.codex import CodexCliProvider

        return CodexCliProvider()
    if provider == "google":
        from app.provider.google import GoogleProvider

        return GoogleProvider(
            api_key=api_key or os.getenv("GOOGLE_API_KEY", ""),
            proxy=os.getenv("GOOGLE_PROXY") or None,
        )
    if provider == "anthropic":
        from app.provider.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            proxy=os.getenv("ANTHROPIC_PROXY") or None,
            # Hard rule: never hit api.anthropic.com directly — route through the
            # configured gateway. See MEMORY:feedback_anthropic_no_direct_api.
            base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
        )
    if model_id.startswith("gemini"):
        from app.provider.google import GoogleProvider

        return GoogleProvider(
            api_key=api_key or os.getenv("GOOGLE_API_KEY", ""),
            proxy=os.getenv("GOOGLE_PROXY") or None,
        )
    if model_id.startswith("claude") or model_id.startswith("anthropic"):
        from app.provider.anthropic import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""),
            proxy=os.getenv("ANTHROPIC_PROXY") or None,
            # Hard rule: never hit api.anthropic.com directly — route through the
            # configured gateway. See MEMORY:feedback_anthropic_no_direct_api.
            base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
        )
    raise ValueError(f"no provider for model_id={model_id!r}")
