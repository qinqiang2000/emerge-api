from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.schemas.reviewed import ReviewedSource
from app.tools.pre_label import get_pending
from app.tools.reviewed import get_reviewed, save_reviewed


router = APIRouter()


class ReviewedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = None
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")


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
