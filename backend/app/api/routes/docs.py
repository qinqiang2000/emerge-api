import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.routes._safety import safe_filename, safe_project_id
from app.config import get_settings
from app.tools.docs import pdf_render_page
from app.workspace.paths import doc_meta_path, doc_path


router = APIRouter()


_IMAGE_MEDIA = {"png": "image/png", "jpg": "image/jpeg"}


@router.get("/lab/projects/{project_id}/docs/by-name/{filename:path}/pages/{page}")
async def get_page(project_id: str, filename: str, page: int) -> FileResponse:
    """Serve a viewable page bitmap for a doc.

    Filename is the only doc handle (post-d_xxx removal). The `:path` converter
    lets percent-encoded names with spaces or dots through; we still
    defensively validate the result via `safe_filename` to reject path
    separators and traversal segments.

    PDF: renders the requested page on demand (cached under
    `docs/.meta/_render/{filename}/p{n}.png`).
    PNG/JPG: page=1 returns the original bytes; any other page is 404. The
    chat thumbnails use this single URL pattern for both image and PDF
    attachments."""
    safe_project_id(project_id)
    safe_filename(filename)
    settings = get_settings()
    meta_p = doc_meta_path(settings.workspace_root, project_id, filename)
    if not meta_p.exists():
        raise HTTPException(status_code=404, detail="doc_not_found")
    meta = json.loads(meta_p.read_text())
    ext = str(meta.get("ext", "")).lower()
    if ext in _IMAGE_MEDIA:
        if page != 1:
            raise HTTPException(status_code=404, detail="page out of range")
        return FileResponse(
            doc_path(settings.workspace_root, project_id, filename),
            media_type=_IMAGE_MEDIA[ext],
        )
    try:
        path = await pdf_render_page(settings.workspace_root, project_id, filename, page=page)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(path, media_type="image/png")
