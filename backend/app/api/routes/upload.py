from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.tools.docs import upload_doc
from app.workspace.staging import StagingError, stage_file


router = APIRouter()


@router.post("/lab/projects/{slug}/upload")
async def upload(slug: str, file: UploadFile = File(...)) -> dict:
    """Upload a doc to `docs/<final_name>`. Response carries the post-dedup
    filename — there is no `doc_id` anymore. The frontend uses this filename
    as the doc handle for every subsequent call (pages, reviewed,
    predictions)."""
    safe_slug(slug)
    settings = get_settings()
    data = await file.read()
    try:
        meta = await upload_doc(settings.workspace_root, slug, data, file.filename or "")
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


@router.post("/lab/uploads/staging")
async def upload_staging(file: UploadFile = File(...)) -> dict[str, Any]:
    """Stage a single file under `workspace/_staging/{stage_token}/`.

    No project is created — the caller will pass the returned `stage_token`
    into the next chat turn's `attachments[i].stage_token`, where the backend
    mints the project and claims the staged file. Cleanup of unclaimed
    staging dirs happens on app startup (see `cleanup_stale`).
    """
    settings = get_settings()
    data = await file.read()
    try:
        info = await stage_file(settings.workspace_root, data, file.filename or "")
    except StagingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return info
