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

        # Vertex (GCP/ADC) vs AI Studio (api_key) is chosen by the SDK's own
        # standard env var so the switch is config, not code. Off by default →
        # live prod keeps using GOOGLE_API_KEY. The offline OCR backfill flips
        # GOOGLE_GENAI_USE_VERTEXAI=true (+ GOOGLE_CLOUD_PROJECT/LOCATION) for its
        # process only, routing the heavy historical pass through GCP/Vertex.
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in (
            "1", "true", "yes",
        )
        return GoogleProvider(
            api_key=api_key or os.getenv("GOOGLE_API_KEY", ""),
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
