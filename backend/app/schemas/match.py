"""Pydantic models for the document-matching (一锚多源核对) layer.

A *match project* references one **anchor** extract project (the primary
document — e.g. the invoice) and a set of **source** extract projects (the
corroborating documents — payment / PO / GRN …). The match prompt declares,
per source, which anchor field maps to which source field and with what
tolerance. `run_match` pairs each anchor doc against the best candidate in
every source and emits a per-anchor "reconcile card".

P0 implements anchor + 1 source; the data model already supports N sources
(`mappings` is keyed by source slug, a card holds a list of pairs).

Hard rules honoured here: these are pure data shapes — no bbox, no document
body, only field values flow through. The `MatchPromptVariant` mirrors
`PromptVariant`'s version-on-change discipline (it cannot reuse the class —
`PromptVariant` is `extra="forbid"` and welds in a `schema` field).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class Tol(BaseModel):
    """Per-key-pair tolerance. `type` picks the comparison primitive:
    - `exact`   — unicode-canonical + id/code casefold equality (no extra args)
    - `number`  — numeric equality within `abs` (default 0.0 = exact number)
    - `date_days` — date equality within `days` calendar days (default 0)
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["exact", "number", "date_days"]
    abs: Optional[float] = None
    days: Optional[int] = None


class KeyMapping(BaseModel):
    """One anchor-field ↔ source-field correspondence with its tolerance."""

    model_config = ConfigDict(extra="forbid")

    anchor: str
    source: str
    tol: Tol


class MatchPromptVariant(BaseModel):
    """Versioned match-rule carrier — the match twin of `PromptVariant`.

    `mappings` is keyed by source-project slug; each value is the list of
    key correspondences for that source. `rules` is free-form NL (the L2
    judge tie-breaker context + human-readable doc), the match analogue of a
    prompt's `global_notes`. `version` + `content_hash` follow the same
    bump-on-content-change discipline `write_prompt` uses.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    prompt_id: str
    label: str = ""
    mappings: dict[str, list[KeyMapping]] = {}
    rules: str = ""
    derived_from: Optional[str] = None
    created_at: str
    updated_at: str
    version: int = 1
    content_hash: Optional[str] = None


class PairVerdict(BaseModel):
    """The judgement for one anchor-doc ↔ one source's chosen doc.

    `doc` is the matched source filename (None when no candidate cleared the
    threshold → `status="missing"`). `score` is matched_keys / total_keys.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    doc: Optional[str] = None
    status: Literal["match", "mismatch", "missing"]
    mismatched_fields: list[str] = []
    reason: Optional[str] = None
    score: float = 0.0


class MatchCard(BaseModel):
    """One anchor document's whole reconcile picture — a pair per source.

    `overall`: all sources matched → `complete`; some matched / some missing
    or mismatched → `partial`; nothing matched at all → `unmatched`.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_doc: str
    pairs: list[PairVerdict] = []
    overall: Literal["complete", "partial", "unmatched"]


class MatchResult(BaseModel):
    """The full output of one `run_match` — a card per anchor doc plus the
    per-source orphans (source docs no anchor claimed)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: str
    anchor_project: str
    source_projects: list[str] = []
    cards: list[MatchCard] = []
    orphans: dict[str, list[str]] = {}
