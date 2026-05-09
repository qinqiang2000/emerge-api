from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.docs import upload_doc


router = APIRouter()


@router.post("/lab/projects/{project_id}/upload")
async def upload(project_id: str, file: UploadFile = File(...)) -> dict[str, str]:
    safe_project_id(project_id)
    settings = get_settings()
    data = await file.read()
    try:
        did = await upload_doc(settings.workspace_root, project_id, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"doc_id": did}
