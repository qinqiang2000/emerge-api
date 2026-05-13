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

    - prompt_id=None resolves to project.active_prompt_id (triggers migration if needed)
    - prompt_id must reference an existing prompts/{id}.json — raises PromptNotFoundError otherwise
    - preserves prompt_id, label, derived_from, created_at; refreshes updated_at
    """
    if prompt_id is None:
        from app.workspace.migrate import migrate_project_if_needed
        await migrate_project_if_needed(workspace, project_id)
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


class PromptInUseError(Exception):
    """Raised when delete_prompt targets a prompt that is the active prompt
    or is referenced by a non-archived experiment."""


async def create_prompt(
    workspace: Path,
    project_id: str,
    *,
    label: str,
    derived_from: str | None = None,
) -> str:
    """Mint a new prompt_id, write prompts/{new_id}.json by cloning the contents
    of either the active prompt (derived_from=None) or a specified same-project
    prompt. Cross-project derived_from is recorded as-is on the new variant
    for lineage display; actual cross-project content cloning lands in M9.5
    (import_prompt). Returns the new prompt_id.
    """
    from app.workspace.ids import new_prompt_id
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    async with project_lock(workspace, project_id):
        if derived_from is None or "/" not in derived_from:
            # Same-project clone (or default = clone active)
            src_id = derived_from if derived_from is not None else (
                await _resolve_prompt_id(workspace, project_id, None)
            )
            src_path = prompt_path(workspace, project_id, src_id)
            if not src_path.exists():
                raise PromptNotFoundError(
                    f"derived_from prompt {src_id} not found in project {project_id}"
                )
            src = PromptVariant(**json.loads(src_path.read_text(encoding="utf-8")))
            cloned_schema = src.schema
            cloned_notes = src.global_notes
            # Record actual src_id as lineage even when caller passed None
            lineage = src_id
        else:
            # Cross-project literal — clone from active prompt in this project,
            # record the lineage string. M9.5 will resolve the real source.
            active = await read_active_prompt(workspace, project_id)
            cloned_schema = active.schema
            cloned_notes = active.global_notes
            lineage = derived_from

        new_id = new_prompt_id()
        now = _now_iso()
        pv = PromptVariant(
            prompt_id=new_id,
            label=label,
            schema=cloned_schema,
            global_notes=cloned_notes,
            derived_from=lineage,
            created_at=now,
            updated_at=now,
        )
        prompts_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(prompt_path(workspace, project_id, new_id), pv.model_dump(mode="json"))
    return new_id


async def switch_active_prompt(workspace: Path, project_id: str, prompt_id: str) -> None:
    """Set project.json.active_prompt_id = prompt_id. Raises PromptNotFoundError
    if the target prompt file does not exist.
    """
    async with project_lock(workspace, project_id):
        pp = prompt_path(workspace, project_id, prompt_id)
        if not pp.exists():
            raise PromptNotFoundError(
                f"cannot switch active: {prompt_id} not found in project {project_id}"
            )
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text(encoding="utf-8"))
        blob["active_prompt_id"] = prompt_id
        atomic_write_json(pj, blob)


async def delete_prompt(workspace: Path, project_id: str, prompt_id: str) -> None:
    """Physically remove prompts/{prompt_id}.json. Blocks deletion of the active
    prompt (PromptInUseError) and of any prompt referenced by a non-archived
    experiment (also PromptInUseError — archive the experiment first).
    """
    async with project_lock(workspace, project_id):
        pp = prompt_path(workspace, project_id, prompt_id)
        if not pp.exists():
            raise PromptNotFoundError(f"{prompt_id} not found in project {project_id}")
        project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
        if project.get("active_prompt_id") == prompt_id:
            raise PromptInUseError(
                f"cannot delete {prompt_id}: it is the active prompt; switch active first"
            )
        from app.tools.experiment import experiments_referencing_prompt
        refs = await experiments_referencing_prompt(workspace, project_id, prompt_id)
        if refs:
            raise PromptInUseError(
                f"cannot delete {prompt_id}: referenced by experiment(s) {refs}; "
                "archive them first"
            )
        pp.unlink()


async def import_prompt(
    workspace: Path,
    *,
    src_pid: str,
    src_prompt_id: str,
    into_pid: str,
    new_label: str | None = None,
) -> str:
    """Clone-at-time copy of a single prompt variant from src_pid to into_pid.

    - new prompt_id is freshly minted (never reuses src_prompt_id, to avoid
      collision with same-named prompts in dest)
    - schema + global_notes are copied verbatim
    - derived_from = f"{src_pid}/{src_prompt_id}" — purely informational lineage
      string; no live link
    - label defaults to src.label when new_label is None
    - autoresearch _candidate/ entries are never importable (out of scope of
      named variants; would be incoherent without the originating job context)
    """
    from app.workspace.ids import new_prompt_id
    from app.workspace.migrate import migrate_project_if_needed

    # Migrate both to current layout so legacy schema.json doesn't surprise us.
    await migrate_project_if_needed(workspace, src_pid)
    await migrate_project_if_needed(workspace, into_pid)

    src_path = prompt_path(workspace, src_pid, src_prompt_id)
    if not src_path.exists():
        raise PromptNotFoundError(
            f"source prompt {src_prompt_id} not found in project {src_pid}"
        )
    src = PromptVariant(**json.loads(src_path.read_text(encoding="utf-8")))

    dst_pj = project_json_path(workspace, into_pid)
    if not dst_pj.exists():
        raise PromptNotFoundError(
            f"destination project {into_pid} not found"
        )

    async with project_lock(workspace, into_pid):
        new_id = new_prompt_id()
        now = _now_iso()
        pv = PromptVariant(
            prompt_id=new_id,
            label=new_label if new_label else src.label,
            schema=src.schema,
            global_notes=src.global_notes,
            derived_from=f"{src_pid}/{src_prompt_id}",
            created_at=now,
            updated_at=now,
        )
        prompts_dir(workspace, into_pid).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            prompt_path(workspace, into_pid, new_id),
            pv.model_dump(mode="json"),
        )
    return new_id
