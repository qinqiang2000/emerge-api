"""Aggregator tool: agent-side pull for rich state of a surface.

Phase 1 dispatches only the `review` surface, in two arities:

* one doc (`filename` given) — review_status, prediction/reviewed presence,
  notes, evidence pages, which experiments have a prediction for it;
* the whole project (`filename` omitted) — counts + one row per doc,
  optionally filtered by `status`.

Both read the same join as `/lab/projects/{slug}/docs` (the listing the
frontend's `useDocs` store renders), via `tools/doc_status.py` — so the agent
and the UI can never hold different opinions about which docs still have no
prediction.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.schemas.extraction import evidence_page
from app.tools.doc_status import (
    REVIEW_STATUSES,
    compact_row,
    project_doc_status,
    status_counts,
)
from app.tools.predictions import get_prediction
from app.tools.reviewed import get_reviewed
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    experiment_prediction_path,
    experiments_dir,
    pending_reviewed_path,
    project_dir,
)


async def get_surface_state(
    workspace: Path,
    surface: str,
    slug: str,
    *,
    filename: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Dispatch by `surface`. Phase 1 supports only 'review'.

    Two arities, on purpose:

    * ``filename`` given → state of that one doc (evidence, notes, which
      experiments ran on it).
    * ``filename`` omitted → the whole project as a table plus counts,
      optionally filtered by ``status``.

    The set form is not a convenience. A read model that only ever answers
    for one item forces every "which docs are still X" question into N calls
    or into shell archaeology against the storage layout — which is exactly
    what happened in prod on 2026-08-14. See ``tools/doc_status.py``.
    """
    if surface != "review":
        return {
            "ok": False,
            "error": {
                "error_code": "surface_unsupported",
                "error_message_en": (
                    f"surface {surface!r} not implemented in phase 1; "
                    f"only 'review' is available"
                ),
            },
        }
    if not filename:
        return await _review_table(workspace, slug, status=status)
    return await _review_state(workspace, slug, filename)


async def _review_table(
    workspace: Path,
    slug: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    """Project-wide review state: counts over every doc + one row per doc.

    ``counts`` is always over the FULL set even when ``status`` filters the
    rows — "50 docs, 1 unprocessed" is the answer, and the denominator is
    half of it.
    """
    if not project_dir(workspace, slug).exists():
        return {
            "ok": False,
            "error": {
                "error_code": "project_not_found",
                "error_message_en": f"no project {slug!r}",
            },
        }
    if status is not None and status not in REVIEW_STATUSES:
        return {
            "ok": False,
            "error": {
                "error_code": "invalid_status",
                "error_message_en": (
                    f"status must be one of {list(REVIEW_STATUSES)}, got {status!r}"
                ),
            },
        }

    rows = await project_doc_status(workspace, slug)
    counts = status_counts(rows)
    selected = [r for r in rows if status is None or r["review_status"] == status]
    return {
        "ok": True,
        "surface": "review",
        "slug": slug,
        "status_filter": status,
        "counts": counts,
        "docs": [compact_row(r) for r in selected],
    }


async def _review_state(
    workspace: Path,
    slug: str,
    filename: str,
) -> dict[str, Any]:
    """Read review-mode disk state for one (slug, filename). Returns a flat
    dict the agent can json-dump verbatim into a reply.

    `review_status`:
      - 'unprocessed' — doc exists but no prediction has been run
      - 'pending'     — prediction exists, no reviewed payload yet
      - 'reviewed'    — reviewed payload exists

    Drift detection (reviewed-but-field-set-differs-from-schema) is NOT
    computed in phase 1; the skill markdown documents the absence so the
    agent doesn't claim it.
    """
    doc = doc_path(workspace, slug, filename)
    if not doc.exists():
        return {
            "ok": False,
            "error": {
                "error_code": "doc_not_found",
                "error_message_en": (
                    f"no doc named {filename!r} in project {slug!r}"
                ),
            },
        }

    meta: dict[str, Any] = {}
    mp = doc_meta_path(workspace, slug, filename)
    if mp.exists():
        try:
            meta = json.loads(mp.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}

    prediction = await get_prediction(workspace, slug, filename)
    reviewed = await get_reviewed(workspace, slug, filename)

    if reviewed is not None:
        review_status = "reviewed"
    elif prediction is not None:
        review_status = "pending"
    else:
        review_status = "unprocessed"

    # Evidence pages: surface the reviewed map if reviewed exists, else the
    # prediction map. Each surfaced entry is `{field_name: page_int_or_null}`
    # per entity index.
    #
    # The on-disk `_evidence` may be either the legacy `{field: int}` shape or
    # the field-source-grounding `{field: {page, source}}` shape. We coalesce to
    # page-only here via `evidence_page` so the AGENT surface stays page-only and
    # shape-stable — the verbatim `source` is locate-render-internal and must not
    # widen the agent's surface_context (keeps review-turn token cost down).
    raw_evidence = None
    if reviewed is not None and isinstance(reviewed.get("_evidence"), list):
        raw_evidence = reviewed["_evidence"]
    elif prediction is not None and isinstance(prediction.get("_evidence"), list):
        raw_evidence = prediction["_evidence"]
    if raw_evidence is not None:
        evidence = [
            {f: evidence_page(entry, f) for f in entry}
            if isinstance(entry, dict)
            else {}
            for entry in raw_evidence
        ]
    else:
        evidence = None

    notes: dict[str, Any] | None = None
    if reviewed is not None and isinstance(reviewed.get("_notes"), dict):
        notes = reviewed["_notes"]

    # Find experiments that have a per-doc prediction for this file. Lets the
    # agent answer "did exp_xyz extract this doc" without a separate list call.
    experiments_with_prediction: list[str] = []
    edir = experiments_dir(workspace, slug)
    if edir.exists():
        for sub in sorted(edir.iterdir()):
            if not sub.is_dir():
                continue
            if experiment_prediction_path(
                workspace, slug, sub.name, filename,
            ).exists():
                experiments_with_prediction.append(sub.name)

    # has_pending is independent of has_prediction / has_reviewed — it's a
    # Pro-labeler draft awaiting boss verification. The doc-list `review_status`
    # enum stays at {unprocessed, pending, reviewed}; visual differentiation
    # for pre-labeled is surfaced via a banner in Review mode (frontend).
    has_pending = pending_reviewed_path(workspace, slug, filename).exists()

    return {
        "ok": True,
        "surface": "review",
        "slug": slug,
        "filename": filename,
        "review_status": review_status,
        "has_prediction": prediction is not None,
        "has_reviewed": reviewed is not None,
        "has_pending": has_pending,
        "page_count": meta.get("page_count"),
        "ext": meta.get("ext"),
        "uploaded_at": meta.get("uploaded_at"),
        "evidence": evidence,
        "notes": notes,
        "entity_count": (
            len(reviewed.get("entities", []))
            if reviewed and isinstance(reviewed.get("entities"), list)
            else len(prediction.get("entities", []))
            if prediction and isinstance(prediction.get("entities"), list)
            else 0
        ),
        "experiments_with_prediction": experiments_with_prediction,
    }
