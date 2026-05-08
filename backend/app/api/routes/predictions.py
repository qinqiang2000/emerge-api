from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.tools.predictions import get_prediction


router = APIRouter()


@router.get("/lab/projects/{project_id}/predictions/{doc_id}")
async def get_doc_prediction(project_id: str, doc_id: str) -> dict:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    payload = await get_prediction(settings.workspace_root, project_id, doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return payload
