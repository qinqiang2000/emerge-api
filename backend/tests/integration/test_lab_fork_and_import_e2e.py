"""End-to-end: fork an existing seeded project, import a prompt back into
the original, then create an experiment that references the imported
prompt — the full §4.1 + §4.2 scenario shapes from the spec."""
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
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_us_invoice(workspace: Path) -> str:
    """Mimic a small migrated us-invoice project — three prompt variants,
    two models, no docs."""
    src_pid = "p_us0000000001"
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
        "active_version_id": "v2",
    })
    for prompt_id, label, schema in (
        ("pr_baseline", "US baseline", [
            {"name": "invoice_no", "type": "string", "description": "", "required": False},
            {"name": "supplier_state", "type": "string", "description": "US state code", "required": False},
        ]),
        ("pr_compact", "compact descriptions", []),
        ("pr_supplier_hint", "supplier 右上角", []),
    ):
        atomic_write_json(prompt_path(workspace, src_pid, prompt_id), {
            "prompt_id": prompt_id, "label": label, "schema": schema,
            "global_notes": "us notes", "derived_from": None,
            "created_at": _now(), "updated_at": _now(),
        })
    for model_id, provider_model_id in (
        ("m_default", "gemini-2.5-flash"),
        ("m_gemma", "gemma-4-12b-it"),
    ):
        atomic_write_json(model_path(workspace, src_pid, model_id), {
            "model_id": model_id, "label": model_id,
            "provider": "google", "provider_model_id": provider_model_id,
            "params": {"temperature": 0.0}, "created_at": _now(),
        })
    return src_pid


def test_fork_then_import_then_experiment_pipeline(workspace: Path) -> None:
    src_pid = _seed_us_invoice(workspace)
    client = TestClient(app)

    # §4.1: fork into UK
    fork_resp = client.post(
        "/lab/projects/fork",
        json={"src_pid": src_pid, "name": "uk-invoice"},
    )
    assert fork_resp.status_code == 200, fork_resp.text
    uk_pid = fork_resp.json()["project_id"]

    # Forked project has the same three prompts and two models
    assert prompt_path(workspace, uk_pid, "pr_baseline").exists()
    assert prompt_path(workspace, uk_pid, "pr_supplier_hint").exists()
    assert model_path(workspace, uk_pid, "m_gemma").exists()
    uk_blob = json.loads(project_json_path(workspace, uk_pid).read_text())
    assert uk_blob["name"] == "uk-invoice"
    assert uk_blob["active_version_id"] is None

    # §4.2 shape: independently — import the UK baseline back into a third
    # project ("B vendor eval") to compare against the US baseline
    b_pid = "p_b00000000001"
    bdir = workspace / b_pid
    bdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, b_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, b_pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, b_pid), {
        "name": "b-eval", "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default", "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, b_pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "B baseline",
        "schema": [], "global_notes": "",
        "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, b_pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {"temperature": 0.0}, "created_at": _now(),
    })

    # Import US baseline AND UK baseline into B
    r1 = client.post(
        f"/lab/projects/{b_pid}/prompts/import",
        json={
            "src_pid": src_pid, "src_prompt_id": "pr_baseline",
            "new_label": "from US",
        },
    )
    assert r1.status_code == 200, r1.text
    from_us_id = r1.json()["prompt_id"]

    r2 = client.post(
        f"/lab/projects/{b_pid}/prompts/import",
        json={
            "src_pid": uk_pid, "src_prompt_id": "pr_baseline",
            "new_label": "from UK",
        },
    )
    assert r2.status_code == 200, r2.text
    from_uk_id = r2.json()["prompt_id"]

    # Both imports landed with cross-project derived_from + fresh ids
    assert from_us_id != "pr_baseline" and from_uk_id != "pr_baseline"
    assert from_us_id != from_uk_id

    us_blob = json.loads(prompt_path(workspace, b_pid, from_us_id).read_text())
    assert us_blob["derived_from"] == f"{src_pid}/pr_baseline"
    uk_blob_imported = json.loads(prompt_path(workspace, b_pid, from_uk_id).read_text())
    assert uk_blob_imported["derived_from"] == f"{uk_pid}/pr_baseline"

    # Imported prompts visible via list_prompts route
    list_resp = client.get(f"/lab/projects/{b_pid}/prompts")
    assert list_resp.status_code == 200
    ids = {p["prompt_id"] for p in list_resp.json()}
    assert from_us_id in ids and from_uk_id in ids
