from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_filename, safe_project_id
from app.config import get_settings
from app.tools.predictions import get_prediction


router = APIRouter()


@router.get("/lab/projects/{project_id}/predictions/{filename:path}")
async def get_doc_prediction(project_id: str, filename: str) -> dict:
    """Fetch the latest draft prediction for a doc. `filename` is the on-disk
    name (the only doc handle)."""
    safe_project_id(project_id)
    safe_filename(filename)
    settings = get_settings()
    payload = await get_prediction(settings.workspace_root, project_id, filename)
    if payload is None:
        raise HTTPException(status_code=404, detail="prediction_not_found")
    return payload
