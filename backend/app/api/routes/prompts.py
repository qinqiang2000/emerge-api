from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.schemas.schema_field import SchemaField
from app.tools.prompt import (
    PromptClearError,
    PromptNotFoundError,
    import_prompt,
    list_prompts,
    read_active_prompt,
    read_prompt,
    switch_active_prompt,
    write_prompt,
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


@router.get("/lab/projects/{slug}/prompts")
async def get_project_prompts(slug: str) -> list[dict]:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    return await list_prompts(workspace, slug)


@router.get("/lab/projects/{slug}/prompts/active")
async def get_project_active_prompt(slug: str) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    pv = await read_active_prompt(workspace, slug)
    return pv.model_dump(mode="json", exclude_none=True)


class _PutActivePromptBody(BaseModel):
    # Raw dicts — validated by SchemaField below so pydantic errors surface
    # field-level details for the UI rather than a generic 422.
    schema: list[dict]
    global_notes: str = ""


@router.put("/lab/projects/{slug}/prompts/active")
async def put_project_active_prompt(slug: str, body: _PutActivePromptBody) -> dict:
    """Direct human edit of the active prompt — bypasses the agent.

    Structural changes (add/remove/rename/retype) are allowed because the
    user is the one driving them. Empty-schema saves are allowed too so the
    user can wipe and restart from a blank slate.
    """
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        fields = [SchemaField(**f) for f in body.schema]
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "invalid_schema_field",
                "error_message_en": str(exc),
            },
        )
    try:
        await write_prompt(
            workspace, slug,
            prompt_id=None,
            schema=fields,
            global_notes=body.global_notes,
            allow_clear=True,
        )
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    except PromptClearError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "prompt_clear_refused", "error_message_en": str(exc)},
        )
    pv = await read_active_prompt(workspace, slug)
    return pv.model_dump(mode="json", exclude_none=True)


@router.post("/lab/projects/{slug}/prompts/{prompt_id}/activate")
async def post_activate_project_prompt(slug: str, prompt_id: str) -> dict:
    """Id-flip mirror of the ``switch_active_prompt`` tool.

    The existing ``PUT .../prompts/active`` is a *content edit* (writes schema
    + notes for whichever prompt is currently active). This route is the pure
    pointer flip: set ``project.json.active_prompt_id`` to ``prompt_id`` and
    return the newly-active ``PromptVersion`` blob. Idempotent — re-activating
    the currently-active prompt is a no-op.
    """
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        await switch_active_prompt(workspace, slug, prompt_id)
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    pv = await read_active_prompt(workspace, slug)
    return pv.model_dump(mode="json", exclude_none=True)


@router.get("/lab/projects/{slug}/prompts/{prompt_id}")
async def get_project_prompt_by_id(slug: str, prompt_id: str) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        pv = await read_prompt(workspace, slug, prompt_id)
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return pv.model_dump(mode="json", exclude_none=True)


class _ImportPromptBody(BaseModel):
    # Field name retained; value is a slug.
    src_pid: str
    src_prompt_id: str
    new_label: str | None = None


@router.post("/lab/projects/{slug}/prompts/import")
async def post_import_prompt(slug: str, body: _ImportPromptBody) -> dict:
    workspace = _project_or_404(slug)
    safe_slug(body.src_pid)
    try:
        new_id = await import_prompt(
            workspace,
            src_slug=body.src_pid,
            src_prompt_id=body.src_prompt_id,
            into_slug=slug,
            new_label=body.new_label,
        )
    except PromptNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found"},
        )
    return {"prompt_id": new_id}
