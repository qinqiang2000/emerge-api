"""M14 — `_run` envelope minting helpers.

The three sites that write a prediction blob (`extract_one`,
`experiment_run`, `pre_label.label_docs`) call `build_stamp` to produce a
`RunStamp` and inject it under `_run` on the payload they atomic-write.

`run_id` format: `r_{ts}_{extract_model_slug}_{prompt_id}` — a stable,
human-readable label. Not an index key; UI / chat narration consumes it.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.schemas.model_config import ModelConfig
from app.schemas.prompt_variant import PromptVariant
from app.schemas.run import RunKind, RunStamp


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _slug_model(extract_model: Optional[str]) -> str:
    """Sanitize a provider model id for inclusion in a filename-safe `run_id`.

    `gemini-2.5-flash` stays as-is; weird characters (slashes, colons, spaces
    from a homebrew variant id) collapse to underscores.
    """
    if not extract_model:
        return "unknown"
    return re.sub(r"[^A-Za-z0-9._-]", "_", extract_model)


def mint_run_id(ts: str, extract_model: Optional[str], prompt_id: Optional[str]) -> str:
    """Build a stable `run_id` label for one prediction write.

    Pure function — caller passes the same `ts` it stamps `RunStamp.ts` with,
    so the id and the timestamp stay in sync.
    """
    return f"r_{ts}_{_slug_model(extract_model)}_{prompt_id or 'unknown'}"


def build_stamp(
    kind: RunKind,
    model_cfg: Optional[ModelConfig],
    prompt_variant: Optional[PromptVariant],
    *,
    extract_model_override: Optional[str] = None,
) -> RunStamp:
    """Mint a `RunStamp` from the already-loaded model + prompt objects.

    `extract_model_override` is for `pre_label`: the labeler model is
    resolved via `_resolve_labeler_model` (not via `read_active_model`), so
    callers pass the resolved provider id directly. For `baseline` /
    `experiment` writes, callers pass `model_cfg` and we read
    `provider_model_id` off it.
    """
    ts = _now_ts()
    model_id = model_cfg.model_id if model_cfg else None
    model_label = model_cfg.label if model_cfg else None
    extract_model = extract_model_override or (
        model_cfg.provider_model_id if model_cfg else None
    )
    prompt_id = prompt_variant.prompt_id if prompt_variant else None
    prompt_label = prompt_variant.label if prompt_variant else None
    return RunStamp(
        run_id=mint_run_id(ts, extract_model, prompt_id),
        ts=ts,
        model_id=model_id,
        extract_model=extract_model,
        model_label=model_label,
        prompt_id=prompt_id,
        prompt_label=prompt_label,
        kind=kind,
    )
