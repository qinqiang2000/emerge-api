from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes._safety import safe_filename, safe_project_id
from app.config import get_settings
from app.schemas.reviewed import ReviewedSource
from app.tools.reviewed import get_reviewed, save_reviewed


router = APIRouter()


class ReviewedBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = None
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")


@router.post("/lab/projects/{project_id}/reviewed/{filename:path}")
async def post_reviewed(
    project_id: str,
    filename: str,
    body: ReviewedBody,
) -> dict:
    """Save reviewed (ground-truth) entities for a doc. Keyed by the doc's
    on-disk filename (the only doc handle)."""
    safe_project_id(project_id)
    safe_filename(filename)
    settings = get_settings()
    await save_reviewed(
        settings.workspace_root,
        project_id,
        filename,
        entities=body.entities,
        source=body.source,
        notes=body.notes,
        evidence=body.evidence,
    )
    return {"ok": True}


@router.get("/lab/projects/{project_id}/reviewed/{filename:path}")
async def get_doc_reviewed(project_id: str, filename: str) -> dict:
    safe_project_id(project_id)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_reviewed(settings.workspace_root, project_id, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="reviewed_not_found")
    return payload
