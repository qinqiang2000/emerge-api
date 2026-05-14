import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.tools.docs import pdf_render_page
from app.workspace.paths import doc_meta_path, doc_path


router = APIRouter()


_IMAGE_MEDIA = {"png": "image/png", "jpg": "image/jpeg"}


@router.get("/lab/projects/{project_id}/docs/{doc_id}/pages/{page}")
async def get_page(project_id: str, doc_id: str, page: int) -> FileResponse:
    """Serve a viewable page bitmap for a doc.

    PDF: renders the requested page on demand (cached under `docs/_render/`).
    PNG/JPG: page=1 returns the original bytes; any other page is 404. This lets
    the chat thumbnails use a single URL pattern for both image and PDF
    attachments."""
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    meta_p = doc_meta_path(settings.workspace_root, project_id, doc_id)
    if not meta_p.exists():
        raise HTTPException(status_code=404, detail="doc_not_found")
    meta = json.loads(meta_p.read_text())
    ext = str(meta.get("ext", "")).lower()
    if ext in _IMAGE_MEDIA:
        if page != 1:
            raise HTTPException(status_code=404, detail="page out of range")
        return FileResponse(
            doc_path(settings.workspace_root, project_id, doc_id, ext),
            media_type=_IMAGE_MEDIA[ext],
        )
    try:
        path = await pdf_render_page(settings.workspace_root, project_id, doc_id, page=page)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(path, media_type="image/png")
