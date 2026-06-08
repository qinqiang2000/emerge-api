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
    def _google() -> Provider:
        from app.provider.google import GoogleProvider

        # Three Gemini surfaces, picked by env (config, not code):
        #   • AI Studio (default)         — GOOGLE_API_KEY, no flag.
        #   • Vertex / "Gemini Enterprise Agent Platform" via API KEY (preferred
        #     Vertex path, no host login) — flag on + a Vertex api key.
        #   • Vertex via ADC (legacy, host gcloud login) — flag on + no api key,
        #     resolves bearer from GOOGLE_CLOUD_PROJECT/LOCATION. Kept for the
        #     offline OCR backfill on hosts that already have ADC.
        # The flag is the SDK's own env var GOOGLE_GENAI_USE_VERTEXAI, or its
        # newer alias GOOGLE_GENAI_USE_ENTERPRISE (the platform's rename).
        def _truthy(name: str) -> bool:
            return os.getenv(name, "").strip().lower() in ("1", "true", "yes")

        use_vertex = _truthy("GOOGLE_GENAI_USE_VERTEXAI") or _truthy(
            "GOOGLE_GENAI_USE_ENTERPRISE"
        )
        # In Vertex mode prefer a dedicated key so a present AI Studio
        # GOOGLE_API_KEY needn't be overwritten; fall back to GOOGLE_API_KEY to
        # match Google's docs (which reuse that var). An empty key → ADC branch.
        if use_vertex:
            key = (
                api_key
                or os.getenv("GOOGLE_VERTEX_API_KEY")
                or os.getenv("GOOGLE_API_KEY", "")
            )
        else:
            key = api_key or os.getenv("GOOGLE_API_KEY", "")
        return GoogleProvider(
            api_key=key,
            proxy=os.getenv("GOOGLE_PROXY") or None,
            use_vertex=use_vertex,
            vertex_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            vertex_location=os.getenv("GOOGLE_CLOUD_LOCATION") or "us-central1",
        )

    if provider == "codex":
        from app.provider.codex import CodexCliProvider

        return CodexCliProvider()
    if provider == "google":
        return _google()
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
        return _google()
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
