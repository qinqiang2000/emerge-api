from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.model import (
    ModelNotFoundError,
    create_model,
    list_models,
    read_active_model,
    read_model,
    write_model,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import model_path, models_dir, project_json_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_active_project(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    models_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "t",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default",
        "label": "Default (gemini-2.0-flash)",
        "provider": "google",
        "provider_model_id": "gemini-2.0-flash",
        "params": {"temperature": 0.0},
        "created_at": _now(),
    })


async def test_read_model_by_id(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mc = await read_model(workspace, pid, "m_default")
    assert mc.provider_model_id == "gemini-2.0-flash"
    assert mc.provider == "google"


async def test_read_model_missing_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(ModelNotFoundError):
        await read_model(workspace, pid, "m_nope")


async def test_read_active_model(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mc = await read_active_model(workspace, pid)
    assert mc.model_id == "m_default"


async def test_create_model_returns_id_with_prefix(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    mid = await create_model(
        workspace, pid,
        label="Gemma 4",
        provider="google",
        provider_model_id="gemma-4-12b-it",
        params={"temperature": 0.0},
    )
    assert mid.startswith("m_")
    mc = await read_model(workspace, pid, mid)
    assert mc.label == "Gemma 4"
    assert mc.provider_model_id == "gemma-4-12b-it"


async def test_write_model_upserts(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # upsert with new label
    await write_model(
        workspace, pid,
        model_id="m_default",
        label="Default (renamed)",
        provider="google",
        provider_model_id="gemini-2.0-flash",
        params={"temperature": 0.1},
    )
    mc = await read_model(workspace, pid, "m_default")
    assert mc.label == "Default (renamed)"
    assert mc.params["temperature"] == 0.1


async def test_list_models_marks_active(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    await create_model(
        workspace, pid,
        label="Sonnet",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
    )
    rows = await list_models(workspace, pid)
    assert len(rows) == 2
    by_label = {r["label"]: r for r in rows}
    assert by_label["Default (gemini-2.0-flash)"]["is_active"] is True
    assert by_label["Sonnet"]["is_active"] is False
