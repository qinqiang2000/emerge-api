"""Aggregator tool: agent-side pull for rich state of a surface.

Phase 1 dispatches only the `review` surface. Returns disk-derived state for
one doc — review_status, prediction/reviewed presence, notes, evidence pages,
and which experiments have a prediction for the doc. The frontend's
`useDocs` store derives the same status from `has_prediction` / `has_reviewed`
on the `/lab/projects/{slug}/docs` listing, so this is the agent-side mirror.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.predictions import get_prediction
from app.tools.reviewed import get_reviewed
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    experiment_prediction_path,
    experiments_dir,
    pending_reviewed_path,
)


async def get_surface_state(
    workspace: Path,
    surface: str,
    slug: str,
    *,
    filename: str | None = None,
) -> dict[str, Any]:
    """Dispatch by `surface`. Phase 1 supports only 'review'."""
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
        return {
            "ok": False,
            "error": {
                "error_code": "surface_missing_param",
                "error_message_en": "review surface requires `filename`",
            },
        }
    return await _review_state(workspace, slug, filename)


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
    # prediction map. Each entry is `{field_name: page_int_or_null}` per
    # entity index. `_evidence` mirrors the on-disk JSON schema.
    if reviewed is not None and isinstance(reviewed.get("_evidence"), list):
        evidence = reviewed["_evidence"]
    elif prediction is not None and isinstance(prediction.get("_evidence"), list):
        evidence = prediction["_evidence"]
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
