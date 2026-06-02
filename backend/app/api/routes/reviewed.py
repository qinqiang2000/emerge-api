import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.schemas.reviewed import ReviewedSource
from app.tools.pre_label import get_pending
from app.tools.reviewed import get_reviewed, save_reviewed
from app.workspace.paths import project_json_path, reviewed_dir


router = APIRouter()


class ReviewedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = None
    # Per-field before/after diff of what the human changed this pass. Optional
    # (absent → None) for backward compat; when present it both lands in the
    # reviewed file and bumps `corrections_since_tune` (see save_reviewed).
    corrections: Optional[dict[str, dict[str, Any]]] = Field(
        default=None, alias="_corrections"
    )
    # Accept both legacy {field: int|null} and new {field: {page, source}} shapes.
    evidence: Optional[list[dict[str, Any]]] = Field(default=None, alias="_evidence")


@router.post("/lab/projects/{slug}/reviewed/{filename:path}")
async def post_reviewed(
    slug: str,
    filename: str,
    body: ReviewedBody,
) -> dict:
    """Save reviewed (ground-truth) entities for a doc. Keyed by the doc's
    on-disk filename (the only doc handle)."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    await save_reviewed(
        settings.workspace_root,
        slug,
        filename,
        entities=body.entities,
        source=body.source,
        notes=body.notes,
        evidence=body.evidence,
        corrections=body.corrections,
    )
    return {"ok": True}


@router.get("/lab/projects/{slug}/reviewed/{filename:path}")
async def get_doc_reviewed(slug: str, filename: str) -> dict:
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_reviewed(settings.workspace_root, slug, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="reviewed_not_found")
    return payload


@router.get("/lab/projects/{slug}/tune-signal")
async def get_tune_signal(slug: str) -> dict:
    """Correction backlog summary that drives the review-bar tune affordance.

    Returns the scalar `corrections_since_tune`, the per-field tally, the
    reviewed-doc count, and a derived `hot_fields` list (fields corrected ≥2
    times — strong "this field's description is wrong" signal). The review bar
    renders a non-chat "optimize this field" button from this, and uses the
    corrected-field set as the focused tune's `target_fields`. Best-effort:
    a missing/garbled project yields zeros, never an error."""
    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    corrections = 0
    by_field: dict[str, int] = {}
    try:
        blob = json.loads(project_json_path(ws, slug).read_text())
        corrections = int(blob.get("corrections_since_tune") or 0)
        raw = blob.get("corrections_by_field")
        if isinstance(raw, dict):
            by_field = {
                str(k): int(v or 0) for k, v in raw.items() if int(v or 0) > 0
            }
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    try:
        rd = reviewed_dir(ws, slug)
        reviewed_count = sum(1 for _ in rd.glob("*.json")) if rd.exists() else 0
    except OSError:
        reviewed_count = 0
    ranked = sorted(by_field.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "corrections_since_tune": corrections,
        "reviewed_count": reviewed_count,
        # Sorted high→low so the FE can name the top field without re-sorting.
        "by_field": [{"field": f, "count": n} for f, n in ranked],
        "hot_fields": [f for f, n in ranked if n >= 2],
        # The corrected-field set = the focused tune's target_fields.
        "corrected_fields": [f for f, _ in ranked],
    }


@router.get("/lab/projects/{slug}/pending/{filename:path}")
async def get_doc_pending(slug: str, filename: str) -> dict:
    """Pro-labeler pending draft for one doc, or 404 if none. The frontend
    falls back to this when `reviewed/` is empty for a doc — and renders a
    banner with the recorded `labeler_model` so the boss knows it's a draft."""
    safe_slug(slug)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_pending(settings.workspace_root, slug, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="pending_not_found")
    return payload
