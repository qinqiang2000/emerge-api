import json
import os
from pathlib import Path

import pytest

from app.tools.publish import (
    PublishNotReadyError,
    freeze_version,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    reviewed_dir,
    schema_path,
    version_path,
    versions_dir,
)


def _ready_project(workspace: Path, pid: str) -> None:
    project_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "p", "project_type": "extraction", "created_at": "x",
        "extract_model": "claude-sonnet-4-6",
        "extract_params": {"temperature": 0.0},
        "autoresearch_proposer_model": None,
        "active_version_id": None,
        "publish_min_macro_f1": 0.7,
    })
    atomic_write_json(schema_path(workspace, pid), [
        {"name": "buyer_name", "type": "string", "description": "x", "required": False},
        {"name": "total_amount", "type": "number", "description": "x", "required": False},
    ])
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]})


@pytest.mark.asyncio
async def test_freeze_writes_v1_immutable(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    out = await freeze_version(tmp_path, pid)
    assert out == {"version_id": "v1"}
    target = version_path(tmp_path, pid, 1)
    assert target.exists()
    blob = json.loads(target.read_text())
    assert blob["version_id"] == "v1"
    assert blob["schema"][0]["name"] == "buyer_name"
    assert blob["model_id"] == "claude-sonnet-4-6"
    mode = os.stat(target).st_mode & 0o777
    assert mode == 0o444


@pytest.mark.asyncio
async def test_freeze_updates_active_version_id(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    await freeze_version(tmp_path, pid)
    project = json.loads(project_json_path(tmp_path, pid).read_text())
    assert project["active_version_id"] == "v1"


@pytest.mark.asyncio
async def test_freeze_v2_increments(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    await freeze_version(tmp_path, pid)
    atomic_write_json(schema_path(tmp_path, pid), [
        {"name": "buyer_name", "type": "string", "description": "x", "required": False},
        {"name": "total_amount", "type": "number", "description": "x", "required": False},
        {"name": "supplier_brn", "type": "string", "description": "x", "required": False},
    ])
    out2 = await freeze_version(tmp_path, pid)
    assert out2 == {"version_id": "v2"}
    project = json.loads(project_json_path(tmp_path, pid).read_text())
    assert project["active_version_id"] == "v2"
    v1 = version_path(tmp_path, pid, 1)
    assert v1.exists()
    assert os.stat(v1).st_mode & 0o777 == 0o444


@pytest.mark.asyncio
async def test_freeze_without_readiness_raises(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    atomic_write_json(schema_path(tmp_path, pid), [])
    with pytest.raises(PublishNotReadyError) as exc:
        await freeze_version(tmp_path, pid)
    assert exc.value.error_code == "not_ready"


@pytest.mark.asyncio
async def test_freeze_force_bypasses_readiness(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    atomic_write_json(schema_path(tmp_path, pid), [])
    out = await freeze_version(tmp_path, pid, force=True)
    assert out["version_id"] == "v1"


@pytest.mark.asyncio
async def test_freeze_includes_global_notes(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _ready_project(tmp_path, pid)
    (project_dir(tmp_path, pid) / "global_notes.md").write_text("Read carefully.")
    await freeze_version(tmp_path, pid)
    blob = json.loads(version_path(tmp_path, pid, 1).read_text())
    assert blob["global_notes"] == "Read carefully."
