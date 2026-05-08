from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.schemas.reviewed import ReviewedSource
from app.tools.reviewed import get_reviewed, save_reviewed


router = APIRouter()


class ReviewedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = None


@router.post("/lab/projects/{project_id}/reviewed/{doc_id}")
async def post_reviewed(
    project_id: str,
    doc_id: str,
    body: ReviewedBody,
) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    await save_reviewed(
        settings.workspace_root,
        project_id,
        doc_id,
        entities=body.entities,
        source=body.source,
        notes=body.notes,
    )
    return {"ok": True}


@router.get("/lab/projects/{project_id}/reviewed/{doc_id}")
async def get_doc_reviewed(project_id: str, doc_id: str) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    payload = await get_reviewed(settings.workspace_root, project_id, doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="reviewed_not_found")
    return payload
