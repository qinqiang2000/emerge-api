from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.model import (
    ModelNotFoundError,
    list_models,
    read_active_model,
    read_model,
)
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(pid: str) -> Path:
    safe_project_id(pid)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, pid)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{project_id}/models")
async def get_project_models(project_id: str) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_models(workspace, project_id)


@router.get("/lab/projects/{project_id}/models/active")
async def get_project_active_model(project_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    mc = await read_active_model(workspace, project_id)
    return mc.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/models/{model_id}")
async def get_project_model_by_id(project_id: str, model_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    try:
        mc = await read_model(workspace, project_id, model_id)
    except ModelNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found"},
        )
    return mc.model_dump(mode="json")
