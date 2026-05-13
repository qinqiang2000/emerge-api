from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_source(workspace: Path) -> str:
    src_pid = "p_src123456789"
    pdir = workspace / src_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, src_pid), {
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v3",
    })
    atomic_write_json(prompt_path(workspace, src_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "US baseline",
        "schema": [{"name": "invoice_no", "type": "string", "description": "d", "required": False}],
        "global_notes": "us notes", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, src_pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0}, "created_at": _now(),
    })
    return src_pid


def test_fork_route_creates_new_project(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": src_pid, "name": "uk-invoice"},
    )
    assert r.status_code == 200, r.text
    new_pid = r.json()["project_id"]
    assert new_pid.startswith("p_") and new_pid != src_pid

    new_blob = json.loads(project_json_path(workspace, new_pid).read_text())
    assert new_blob["name"] == "uk-invoice"
    assert new_blob["active_version_id"] is None
    assert prompt_path(workspace, new_pid, "pr_baseline").exists()
    assert model_path(workspace, new_pid, "m_default").exists()


def test_fork_route_404_on_missing_source(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": "p_doesnotexist", "name": "x"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"


def test_fork_route_rejects_invalid_src_pid(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/fork",
        json={"src_pid": "../etc/passwd", "name": "x"},
    )
    assert r.status_code == 400


def test_import_prompt_route_clones_into_dest(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    dst_pid = "p_dst123456789"
    pdir = workspace / dst_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, dst_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, dst_pid), {
        "name": "b-eval", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, dst_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "dst", "schema": [],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{dst_pid}/prompts/import",
        json={
            "src_pid": src_pid,
            "src_prompt_id": "pr_baseline",
            "new_label": "from US",
        },
    )
    assert r.status_code == 200, r.text
    new_id = r.json()["prompt_id"]
    assert new_id.startswith("pr_") and new_id != "pr_baseline"

    imported = json.loads(prompt_path(workspace, dst_pid, new_id).read_text())
    assert imported["label"] == "from US"
    assert imported["derived_from"] == f"{src_pid}/pr_baseline"
    assert imported["schema"][0]["name"] == "invoice_no"


def test_import_prompt_route_404_on_missing_src_prompt(workspace: Path) -> None:
    src_pid = _seed_source(workspace)
    dst_pid = "p_dst123456789"
    pdir = workspace / dst_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, dst_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, dst_pid), {
        "name": "x", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, dst_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "x", "schema": [],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{dst_pid}/prompts/import",
        json={
            "src_pid": src_pid,
            "src_prompt_id": "pr_does_not_exist",
        },
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "prompt_not_found"
