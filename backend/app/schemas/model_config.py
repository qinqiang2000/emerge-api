from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Provider = Literal["anthropic", "openai", "google"]


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    model_id: str
    label: str
    provider: Provider
    provider_model_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str


def infer_provider_from_model_id(provider_model_id: str) -> Provider:
    mid = provider_model_id.lower()
    if mid.startswith("claude-"):
        return "anthropic"
    if mid.startswith("gpt-") or mid.startswith("o1-") or mid.startswith("o3-"):
        return "openai"
    if mid.startswith("gemini-") or mid.startswith("gemma-"):
        return "google"
    return "google"
