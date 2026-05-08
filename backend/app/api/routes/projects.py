import json

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.tools.projects import list_projects
from app.workspace.paths import project_json_path


router = APIRouter()


@router.get("/lab/projects")
async def get_projects() -> list[dict]:
    settings = get_settings()
    return await list_projects(settings.workspace_root)


@router.get("/lab/projects/{project_id}")
async def get_project(project_id: str) -> dict:
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, project_id)
    if not pj.exists():
        raise HTTPException(status_code=404, detail="project_not_found")
    blob = json.loads(pj.read_text())
    return {"project_id": project_id, **blob}
