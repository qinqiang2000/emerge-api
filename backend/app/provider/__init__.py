"""Provider factory: pick an adapter by model_id prefix."""
import os
from typing import Optional

from app.provider.base import Provider


def get_provider_for_model(model_id: str, *, api_key: Optional[str] = None) -> Provider:
    """Returns an extractor Provider for the given model_id.

    Reads API keys from environment unless explicitly passed.
    """
    if model_id.startswith("gemini"):
        from app.provider.google import GoogleProvider

        return GoogleProvider(api_key=api_key or os.getenv("GOOGLE_API_KEY", ""))
    if model_id.startswith("claude") or model_id.startswith("anthropic"):
        from app.provider.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""))
    raise ValueError(f"no provider for model_id={model_id!r}")
