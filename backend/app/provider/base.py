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
    # Output-side tokens for the VISIBLE answer, exactly as the provider counts
    # them. Deliberately unchanged in meaning since it was introduced, so a
    # number recorded months ago stays comparable with one recorded today.
    output_tokens: int = 0
    # Reasoning / "thinking" tokens the provider reports SEPARATELY from
    # `output_tokens` — output-priced tokens that are NOT already inside the
    # count above. Gemini 2.5+ is the case that forces this: the SDK documents
    # `total_token_count` as prompt + candidates + tool_use_prompt + thoughts,
    # i.e. `thoughts_token_count` is disjoint from `candidates_token_count`,
    # and on gemini-3-flash's default thinking level it dwarfs the visible
    # output (measured 5630 thoughts vs 819 candidates on one PDF extract).
    #
    # Stays 0 for Anthropic, OpenAI Chat Completions and OpenAI Responses,
    # whose usage already folds reasoning INTO the output count and exposes it
    # only as a `*_details.reasoning_tokens` SUB-total — populating it there
    # would double-count. The invariant every adapter must uphold is that
    # `output_tokens + thinking_tokens` covers all output-billed tokens exactly
    # once, which is what `total_output_tokens` below relies on.
    thinking_tokens: int = 0

    @property
    def total_output_tokens(self) -> int:
        """Every output-priced token. Use this for cost/spend, never
        `output_tokens` alone — that one omits Gemini's thinking tokens."""
        return self.output_tokens + self.thinking_tokens


@runtime_checkable
class Provider(Protocol):
    # Whether the adapter can send a `DocumentBlock` (application/pdf) straight
    # to the API and have the model READ it visually. Anthropic and Google both
    # rasterize PDF pages server-side, so they accept the raw bytes. OpenAI-
    # compatible `image_url` does not (DashScope 400s: "image format is
    # illegal"). When False, callers must rasterize PDF pages to images first —
    # see `app.tools.schema.doc_to_blocks`.
    supports_pdf: bool = True

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
