from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_project_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    chats_dir,
    docs_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    versions_dir,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_status(pdir: Path, blob: dict[str, Any]) -> str:
    if blob.get("active_version_id"):
        return "live"
    # Post-M9.1: presence of non-empty schema lives in prompts/{active_prompt_id}.json
    active_pid = blob.get("active_prompt_id")
    if active_pid:
        pp = pdir / "prompts" / f"{active_pid}.json"
        if pp.exists():
            try:
                pv = json.loads(pp.read_text())
                if isinstance(pv.get("schema"), list) and len(pv["schema"]) > 0:
                    return "draft"
            except (json.JSONDecodeError, OSError):
                pass
    # Legacy fallback (pre-migration): detect by schema.json
    sp = pdir / "schema.json"
    if sp.exists():
        try:
            fields = json.loads(sp.read_text())
            if isinstance(fields, list) and len(fields) > 0:
                return "draft"
        except (json.JSONDecodeError, OSError):
            pass
    return "empty"


async def rename_project(
    workspace: Path,
    project_id: str,
    *,
    name: str,
) -> None:
    """Set `project.json.name`. Used by the agent on the first turn after
    `chat_turn` auto-mints a placeholder-named project (empty-hero drop
    flow) — once the agent can read the user's intent, it should rename
    the project to something meaningful.

    Does not move the project directory or change the project_id. Idempotent:
    re-applying the same name is a no-op-ish write.
    """
    from app.workspace.migrate import migrate_project_if_needed

    name = (name or "").strip()
    if not name:
        raise ValueError("name must be non-empty")
    if len(name) > 200:
        raise ValueError("name too long (>200 chars)")
    await migrate_project_if_needed(workspace, project_id)
    pj = project_json_path(workspace, project_id)
    if not pj.exists():
        raise FileNotFoundError(f"project not found: {project_id}")
    async with project_lock(workspace, project_id):
        blob = json.loads(pj.read_text())
        blob["name"] = name
        atomic_write_json(pj, blob)


async def create_project(
    workspace: Path,
    *,
    name: str,
    project_type: str = "extraction",
) -> str:
    from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
    from app.schemas.prompt_variant import PromptVariant
    from app.workspace.paths import model_path, models_dir, prompt_path, prompts_dir

    pid = new_project_id()
    pdir = project_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=False)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    chats_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, pid).mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    now = _now_iso()

    pv = PromptVariant(
        prompt_id="pr_baseline",
        label="Baseline",
        schema=[],
        global_notes="",
        derived_from=None,
        created_at=now,
        updated_at=now,
    )
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), pv.model_dump(mode="json"))

    mc = ModelConfig(
        model_id="m_default",
        label=f"Default ({settings.default_extract_model})",
        provider=infer_provider_from_model_id(settings.default_extract_model),
        provider_model_id=settings.default_extract_model,
        params={"temperature": 0.0},
        created_at=now,
    )
    atomic_write_json(model_path(workspace, pid, "m_default"), mc.model_dump(mode="json"))

    blob = {
        "name": name,
        "project_type": project_type,
        "created_at": now,
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
        "autoresearch_proposer_model": None,
        "extract_model": settings.default_extract_model,
        "extract_params": {"temperature": 0.0},
    }
    atomic_write_json(project_json_path(workspace, pid), blob)

    # schema.json is intentionally NOT written for new projects.
    return pid


async def list_projects(workspace: Path) -> list[dict[str, Any]]:
    from app.workspace.migrate import migrate_project_if_needed

    if not workspace.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        pj = child / "project.json"
        if not pj.exists():
            continue
        await migrate_project_if_needed(workspace, child.name)
        blob = json.loads(pj.read_text())
        out.append({
            "project_id": child.name,
            "status": _project_status(child, blob),
            **blob,
        })
    return out


async def update_project(workspace: Path, project_id: str, patch: dict[str, Any]) -> None:
    async with project_lock(workspace, project_id):
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text())
        blob.update(patch)
        atomic_write_json(pj, blob)
