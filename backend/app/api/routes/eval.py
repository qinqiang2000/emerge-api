from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.score import run_eval
from app.workspace.paths import project_json_path, schema_path


router = APIRouter()


@router.post("/lab/projects/{project_id}/eval")
async def post_eval(project_id: str) -> dict:
    safe_project_id(project_id)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    if not schema_path(settings.workspace_root, project_id).exists():
        raise HTTPException(status_code=404, detail="schema_not_found")
    result = await run_eval(settings.workspace_root, project_id)
    return result.model_dump(mode="json")
