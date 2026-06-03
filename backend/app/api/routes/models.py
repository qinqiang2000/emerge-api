from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.tools.model import (
    ModelNotFoundError,
    list_models,
    read_active_model,
    read_model,
    switch_active_model,
)
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import project_json_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    pj = project_json_path(current_ws(), slug)
    if not pj.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return current_ws()


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


class _PutActiveModelBody(BaseModel):
    model_id: str


@router.put("/lab/projects/{slug}/models/active")
async def put_project_active_model(slug: str, body: _PutActiveModelBody) -> dict:
    """Direct human switch of the active model — bypasses the agent.

    Last-writer-wins semantics under the project lock (mirrors the
    `PUT .../prompts/active` shape). 404 if the target model_id is unknown
    in this project.
    """
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        await switch_active_model(workspace, slug, body.model_id)
    except ModelNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found"},
        )
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
