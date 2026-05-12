from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.model_config import ModelConfig, Provider
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_model_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    model_path,
    models_dir,
    project_json_path,
)


class ModelNotFoundError(Exception):
    """Raised when read_model targets a model_id that does not exist on disk."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def read_model(workspace: Path, project_id: str, model_id: str) -> ModelConfig:
    mp = model_path(workspace, project_id, model_id)
    if not mp.exists():
        raise ModelNotFoundError(f"{model_id} not found in project {project_id}")
    return ModelConfig(**json.loads(mp.read_text(encoding="utf-8")))


async def read_active_model(workspace: Path, project_id: str) -> ModelConfig:
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_model_id")
    if not active:
        raise ModelNotFoundError(
            f"project {project_id} has no active_model_id; cannot resolve active model"
        )
    return await read_model(workspace, project_id, active)


async def write_model(
    workspace: Path,
    project_id: str,
    *,
    model_id: str,
    label: str,
    provider: Provider,
    provider_model_id: str,
    params: dict[str, Any] | None = None,
) -> None:
    """Upsert a model config. created_at is preserved on update, set fresh on create."""
    async with project_lock(workspace, project_id):
        mp = model_path(workspace, project_id, model_id)
        models_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        if mp.exists():
            existing = ModelConfig(**json.loads(mp.read_text(encoding="utf-8")))
            created = existing.created_at
        else:
            created = _now_iso()
        mc = ModelConfig(
            model_id=model_id,
            label=label,
            provider=provider,
            provider_model_id=provider_model_id,
            params=params or {},
            created_at=created,
        )
        atomic_write_json(mp, mc.model_dump(mode="json"))


async def create_model(
    workspace: Path,
    project_id: str,
    *,
    label: str,
    provider: Provider,
    provider_model_id: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Mint a new model_id and write the config. Returns the new model_id."""
    mid = new_model_id()
    await write_model(
        workspace, project_id,
        model_id=mid,
        label=label,
        provider=provider,
        provider_model_id=provider_model_id,
        params=params,
    )
    return mid


async def list_models(workspace: Path, project_id: str) -> list[dict]:
    md = models_dir(workspace, project_id)
    if not md.exists():
        return []
    project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    active = project.get("active_model_id")
    out: list[dict] = []
    for child in sorted(md.iterdir()):
        if not child.is_file() or not child.name.endswith(".json"):
            continue
        try:
            mc = ModelConfig(**json.loads(child.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        out.append({
            "model_id": mc.model_id,
            "label": mc.label,
            "provider": mc.provider,
            "provider_model_id": mc.provider_model_id,
            "is_active": mc.model_id == active,
            "created_at": mc.created_at,
        })
    return out


class ModelInUseError(Exception):
    """Raised when delete_model targets the active model (or, in later milestones,
    a model referenced by a non-archived experiment).
    """


async def switch_active_model(workspace: Path, project_id: str, model_id: str) -> None:
    """Set project.json.active_model_id = model_id. Raises ModelNotFoundError if
    the target model file does not exist.
    """
    async with project_lock(workspace, project_id):
        mp = model_path(workspace, project_id, model_id)
        if not mp.exists():
            raise ModelNotFoundError(
                f"cannot switch active: {model_id} not found in project {project_id}"
            )
        pj = project_json_path(workspace, project_id)
        blob = json.loads(pj.read_text(encoding="utf-8"))
        blob["active_model_id"] = model_id
        atomic_write_json(pj, blob)


async def delete_model(workspace: Path, project_id: str, model_id: str) -> None:
    """Physically remove models/{model_id}.json. Blocks deletion of the active
    model (ModelInUseError). M9.3 extends this with experiment-reference checks.
    """
    async with project_lock(workspace, project_id):
        mp = model_path(workspace, project_id, model_id)
        if not mp.exists():
            raise ModelNotFoundError(f"{model_id} not found in project {project_id}")
        project = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
        if project.get("active_model_id") == model_id:
            raise ModelInUseError(
                f"cannot delete {model_id}: it is the active model; switch active first"
            )
        mp.unlink()
