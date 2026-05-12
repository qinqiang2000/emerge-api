from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


class PromptNotFoundError(Exception):
    """Raised when read_prompt or write_prompt targets a prompt_id that does not exist on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_prompt_id(workspace: Path, project_id: str, prompt_id: str | None) -> str:
    if prompt_id is not None:
        return prompt_id
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_prompt_id")
    if not active:
        raise PromptNotFoundError(
            f"project {project_id} has no active_prompt_id; cannot resolve None"
        )
    return active


async def read_prompt(workspace: Path, project_id: str, prompt_id: str) -> PromptVariant:
    pp = prompt_path(workspace, project_id, prompt_id)
    if not pp.exists():
        raise PromptNotFoundError(f"{prompt_id} not found in project {project_id}")
    blob = json.loads(pp.read_text(encoding="utf-8"))
    return PromptVariant(**blob)


async def read_active_prompt(workspace: Path, project_id: str) -> PromptVariant:
    resolved = await _resolve_prompt_id(workspace, project_id, None)
    return await read_prompt(workspace, project_id, resolved)


async def write_prompt(
    workspace: Path,
    project_id: str,
    *,
    prompt_id: str | None,
    schema: list[SchemaField],
    global_notes: str = "",
) -> str:
    """Mutate an existing prompt variant. Returns the resolved prompt_id.

    - prompt_id=None resolves to project.active_prompt_id
    - prompt_id must reference an existing prompts/{id}.json — raises PromptNotFoundError otherwise
    - preserves prompt_id, label, derived_from, created_at; refreshes updated_at
    """
    async with project_lock(workspace, project_id):
        resolved = await _resolve_prompt_id(workspace, project_id, prompt_id)
        pp = prompt_path(workspace, project_id, resolved)
        if not pp.exists():
            raise PromptNotFoundError(f"{resolved} not found in project {project_id}")
        existing = PromptVariant(**json.loads(pp.read_text(encoding="utf-8")))
        updated = PromptVariant(
            prompt_id=existing.prompt_id,
            label=existing.label,
            schema=schema,
            global_notes=global_notes,
            derived_from=existing.derived_from,
            created_at=existing.created_at,
            updated_at=_now_iso(),
        )
        atomic_write_json(pp, updated.model_dump(mode="json"))
    return resolved


async def list_prompts(workspace: Path, project_id: str) -> list[dict]:
    """Returns one row per prompt variant on disk, marking the active one."""
    pd = prompts_dir(workspace, project_id)
    if not pd.exists():
        return []
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_prompt_id")
    out: list[dict] = []
    for child in sorted(pd.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            pv = PromptVariant(**json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "prompt_id": pv.prompt_id,
            "label": pv.label,
            "derived_from": pv.derived_from,
            "is_active": pv.prompt_id == active,
            "created_at": pv.created_at,
            "updated_at": pv.updated_at,
        })
    return out
