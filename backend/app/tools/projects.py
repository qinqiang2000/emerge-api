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
    schema_path,
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


async def create_project(
    workspace: Path,
    *,
    name: str,
    project_type: str = "extraction",
) -> str:
    pid = new_project_id()
    pdir = project_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=False)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    chats_dir(workspace, pid).mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    blob = {
        "name": name,
        "project_type": project_type,
        "created_at": _now_iso(),
        "extract_model": settings.default_extract_model,
        "extract_params": {"temperature": 0.0},
        "autoresearch_proposer_model": None,
        "active_version_id": None,
    }
    atomic_write_json(project_json_path(workspace, pid), blob)
    atomic_write_json(schema_path(workspace, pid), [])
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
