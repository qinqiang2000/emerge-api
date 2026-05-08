from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text"] = "text"
    text: str


class ImageBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["image"] = "image"
    media_type: str  # "image/png", "image/jpeg"
    data_b64: str


class DocumentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["document"] = "document"
    media_type: str  # "application/pdf"
    data_b64: str


ContentBlock = TextBlock | ImageBlock | DocumentBlock


class ProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_json: dict[str, Any]
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class Provider(Protocol):
    async def extract(
        self,
        *,
        model_id: str,
        system_prompt: str,
        user_content: list[ContentBlock],
        response_schema: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> ProviderResult:
        """Extract structured JSON from input. Adapter handles retry/backoff internally.

        Returns raw_json validated against response_schema (best-effort, may still need
        downstream pydantic validation).
        """
        ...
