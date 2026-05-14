from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.docs import upload_doc


router = APIRouter()


@router.post("/lab/projects/{project_id}/upload")
async def upload(project_id: str, file: UploadFile = File(...)) -> dict:
    """Upload a doc to `docs/<final_name>`. Response carries the post-dedup
    filename — there is no `doc_id` anymore. The frontend uses this filename
    as the doc handle for every subsequent call (pages, reviewed,
    predictions)."""
    safe_project_id(project_id)
    settings = get_settings()
    data = await file.read()
    try:
        meta = await upload_doc(settings.workspace_root, project_id, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "filename": meta["filename"],
        "ext": meta["ext"],
        "page_count": meta["page_count"],
        "sha256": meta["sha256"],
        "uploaded_at": meta["uploaded_at"],
        "original_name": meta["original_name"],
    }
