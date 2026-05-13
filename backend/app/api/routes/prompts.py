from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.tools.prompt import (
    PromptNotFoundError,
    import_prompt,
    list_prompts,
    read_active_prompt,
    read_prompt,
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


@router.get("/lab/projects/{project_id}/prompts")
async def get_project_prompts(project_id: str) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_prompts(workspace, project_id)


@router.get("/lab/projects/{project_id}/prompts/active")
async def get_project_active_prompt(project_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    pv = await read_active_prompt(workspace, project_id)
    return pv.model_dump(mode="json")


@router.get("/lab/projects/{project_id}/prompts/{prompt_id}")
async def get_project_prompt_by_id(project_id: str, prompt_id: str) -> dict:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    try:
        pv = await read_prompt(workspace, project_id, prompt_id)
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return pv.model_dump(mode="json")


class _ImportPromptBody(BaseModel):
    src_pid: str
    src_prompt_id: str
    new_label: str | None = None


@router.post("/lab/projects/{project_id}/prompts/import")
async def post_import_prompt(project_id: str, body: _ImportPromptBody) -> dict:
    workspace = _project_or_404(project_id)
    safe_project_id(body.src_pid)
    try:
        new_id = await import_prompt(
            workspace,
            src_pid=body.src_pid,
            src_prompt_id=body.src_prompt_id,
            into_pid=project_id,
            new_label=body.new_label,
        )
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return {"prompt_id": new_id}
