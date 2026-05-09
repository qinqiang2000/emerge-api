from fastapi import APIRouter

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.score import run_eval


router = APIRouter()


@router.post("/lab/projects/{project_id}/eval")
async def post_eval(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    result = await run_eval(settings.workspace_root, project_id)
    return result.model_dump(mode="json")
