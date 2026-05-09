from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.routes._safety import safe_doc_id, safe_project_id
from app.config import get_settings
from app.tools.docs import pdf_render_page


router = APIRouter()


@router.get("/lab/projects/{project_id}/docs/{doc_id}/pages/{page}")
async def get_page(project_id: str, doc_id: str, page: int) -> FileResponse:
    safe_project_id(project_id)
    safe_doc_id(doc_id)
    settings = get_settings()
    try:
        path = await pdf_render_page(settings.workspace_root, project_id, doc_id, page=page)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FileResponse(path, media_type="image/png")
