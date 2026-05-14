from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_slug
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


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    pj = project_json_path(settings.workspace_root, slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{slug}/models")
async def get_project_models(slug: str) -> list[dict]:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    return await list_models(workspace, slug)


@router.get("/lab/projects/{slug}/models/active")
async def get_project_active_model(slug: str) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    mc = await read_active_model(workspace, slug)
    return mc.model_dump(mode="json")


@router.get("/lab/projects/{slug}/models/{model_id}")
async def get_project_model_by_id(slug: str, model_id: str) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        mc = await read_model(workspace, slug, model_id)
    except ModelNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found"},
        )
    return mc.model_dump(mode="json")
