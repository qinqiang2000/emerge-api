"""M14 — `_run` envelope on prediction blobs.

A `RunStamp` answers "which (model, prompt) produced this prediction?"
inline on the blob itself, so consumers (score, matrix UI, review tabstrip,
chat narration) don't each reinvent the resolution from `project.json` /
experiment meta. See `docs/superpowers/plans/2026-05-21-m14-run-as-noun.md`.

`run_id` is a stable label per write — not an index key. The prediction blob
is still identified by (slug, filename) for retrieval; `run_id` only powers
UI display and chat anchoring.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

RunKind = Literal["baseline", "experiment", "pre_label"]


class RunStamp(BaseModel):
    """Self-identifying envelope on a prediction blob — answers "which
    (model, prompt) produced this?" without a downstream resolver."""
    model_config = ConfigDict(extra="forbid")
    run_id: str
    ts: str
    model_id: Optional[str] = None
    extract_model: Optional[str] = None
    model_label: Optional[str] = None
    prompt_id: Optional[str] = None
    prompt_label: Optional[str] = None
    kind: RunKind
