"""Pydantic model for field-source-grounding locate results.

A :class:`FieldLocation` is a render-layer artifact: it carries the bbox rects
(PDF point units) where an extracted field's value was located in the document.

Hard rule: this model lives ONLY in the render path (locate HTTP endpoint →
review viewer). ``rects`` are bbox coordinates and must NEVER be fed into any
LLM prompt (extract / labeler / proposer / autoresearch). The locate endpoint
is deliberately NOT a @tool for exactly this reason — see app/tools/locate.py
and docs/superpowers/INSIGHTS.md #7.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# Match tiers, strongest → weakest. ``none`` means the value could not be
# located in the document text (e.g. a derived/computed field with no literal
# source).
LocateStatus = Literal["exact", "fuzzy", "normalized", "quote", "none"]


class FieldLocation(BaseModel):
    """One extracted field's location in the source document.

    ``rects`` are ``[x0, y0, x1, y1]`` in PDF point units (pixels for raster
    docs) — the same units textlayer emits, so the frontend can paint them with
    ``(x0 / page_w) * 100%`` etc. A value spanning multiple spans (e.g. wrapped
    lines) yields multiple rects.
    """

    entity_index: int
    path: str
    rects: list[list[float]] = Field(default_factory=list)
    page: Optional[int] = None
    status: LocateStatus = "none"
    score: float = 0.0


class QuoteLocation(BaseModel):
    """One verbatim quote's location in the source document.

    Mirrors :class:`FieldLocation` but is keyed by the *input index* of the
    quote (audit evidence quotes, board annotations, …) instead of an
    (entity, field-path) pair. Same units / same render-only hard rule:
    ``rects`` flow only through the locate-quotes HTTP render route, never
    into any LLM prompt or agent tool result.
    """

    index: int
    rects: list[list[float]] = Field(default_factory=list)
    page: Optional[int] = None
    status: LocateStatus = "none"
    score: float = 0.0
