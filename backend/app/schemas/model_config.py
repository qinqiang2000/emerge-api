from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


Provider = Literal["anthropic", "openai", "google", "codex", "bedrock_mantle"]


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    model_id: str
    label: str
    provider: Provider
    provider_model_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    base_url: str | None = None       # per-model gateway；None → 回退全局 env
    api_key_env: str | None = None    # 环境变量名，NOT 明文 key


def infer_provider_from_model_id(provider_model_id: str) -> Provider:
    mid = provider_model_id.lower()
    # Bedrock-mantle ids are dot-namespaced by vendor ("openai.gpt-5.6-terra"),
    # which is what separates them from a direct OpenAI id ("gpt-5.6"). Checked
    # before the bare-vendor branches so the dotted form never falls through to
    # the plain openai/anthropic adapters, which speak the wrong wire shape.
    if "." in mid.split("-")[0]:
        return "bedrock_mantle"
    if mid.startswith("claude-"):
        return "anthropic"
    if mid.startswith("gpt-") or mid.startswith("o1-") or mid.startswith("o3-"):
        return "openai"
    if mid.startswith("gemini-") or mid.startswith("gemma-"):
        return "google"
    return "google"
