import json
from pathlib import Path

import pytest

from app.tools.publish import readiness_check
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    jobs_dir,
    metrics_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    reviewed_dir,
    schema_path,
    versions_dir,
)


def _bootstrap_project(
    workspace: Path,
    pid: str,
    *,
    schema_fields=None,
    extract_model="claude-sonnet-4-6",
    publish_min_macro_f1=0.7,
    active_version_id=None,
) -> None:
    project_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "p", "project_type": "extraction", "created_at": "x",
        "extract_model": extract_model, "extract_params": {"temperature": 0.0},
        "autoresearch_proposer_model": None,
        "active_version_id": active_version_id,
        "publish_min_macro_f1": publish_min_macro_f1,
    })
    schema = schema_fields if schema_fields is not None else [
        {"name": "buyer_name", "type": "string", "description": "name", "required": False},
        {"name": "total_amount", "type": "number", "description": "amt", "required": False},
    ]
    atomic_write_json(schema_path(workspace, pid), schema)


def _add_reviewed(workspace, pid, doc_id, entities) -> None:
    atomic_write_json(reviewed_dir(workspace, pid) / f"{doc_id}.json",
                      {"entities": entities, "source": "manual"})


def _add_prediction(workspace, pid, doc_id, entities) -> None:
    atomic_write_json(predictions_draft_dir(workspace, pid) / f"{doc_id}.json",
                      {"entities": entities})


@pytest.mark.asyncio
async def test_empty_schema_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid, schema_fields=[])
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    keys_failing = [c["key"] for c in out["checks"] if c["status"] == "fail"]
    assert "schema_non_empty" in keys_failing


@pytest.mark.asyncio
async def test_no_reviewed_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid)
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    assert any(c["key"] == "reviewed_and_f1" and c["status"] == "fail" for c in out["checks"])


@pytest.mark.asyncio
async def test_passing_minimal_setup(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid)
    for i in range(3):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, [{"buyer_name": "ACME", "total_amount": 100.0}])
        _add_prediction(tmp_path, pid, did, [{"buyer_name": "ACME", "total_amount": 100.0}])
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is True
    assert out["macro_f1"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_low_f1_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid, publish_min_macro_f1=0.7)
    for i in range(3):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, [{"buyer_name": "ACME", "total_amount": 100.0}])
        _add_prediction(tmp_path, pid, did, [{"buyer_name": "WRONG", "total_amount": 999.0}])
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    assert any(c["key"] == "reviewed_and_f1" and c["status"] == "fail" for c in out["checks"])


@pytest.mark.asyncio
async def test_borderline_f1_warns(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid, publish_min_macro_f1=0.7)
    docs = [
        ([{"buyer_name": "ACME", "total_amount": 100.0}], [{"buyer_name": "ACME", "total_amount": 100.0}]),
        ([{"buyer_name": "ACME", "total_amount": 100.0}], [{"buyer_name": "ACME", "total_amount": 100.0}]),
        ([{"buyer_name": "ACME", "total_amount": 100.0}], [{"buyer_name": "ACME", "total_amount": 100.0}]),
        ([{"buyer_name": "BCD", "total_amount": 200.0}], [{"buyer_name": "WRONG", "total_amount": 200.0}]),
    ]
    for i, (rv, pr) in enumerate(docs):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, rv)
        _add_prediction(tmp_path, pid, did, pr)
    out = await readiness_check(tmp_path, pid)
    assert 0.7 <= out["macro_f1"] < 1.0
    if 0.7 <= out["macro_f1"] < 0.85:
        assert any(s["key"] == "f1_borderline" for s in out["soft_warnings"])


@pytest.mark.asyncio
async def test_orphan_reviewed_field_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid)
    for i in range(3):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, [{"buyer_name": "ACME", "ghost_field": "x"}])
        _add_prediction(tmp_path, pid, did, [{"buyer_name": "ACME"}])
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    assert any(c["key"] == "reviewed_fields_in_schema" and c["status"] == "fail" for c in out["checks"])


@pytest.mark.asyncio
async def test_running_job_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(tmp_path, pid)
    for i in range(3):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, [{"buyer_name": "ACME", "total_amount": 100.0}])
        _add_prediction(tmp_path, pid, did, [{"buyer_name": "ACME", "total_amount": 100.0}])
    jd = jobs_dir(tmp_path, pid)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "j_abc123def456.jsonl").write_text(
        json.dumps({"type": "started", "ts": "x"}) + "\n"
        + json.dumps({"type": "turn", "ts": "x", "turn": 1, "macro_f1": 0.5}) + "\n"
    )
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    assert any(c["key"] == "no_running_jobs" and c["status"] == "fail" for c in out["checks"])


@pytest.mark.asyncio
async def test_breaking_change_against_prev_active_fails(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bootstrap_project(
        tmp_path, pid,
        schema_fields=[
            {"name": "buyer_name", "type": "string", "description": "x", "required": False},
        ],
        active_version_id="v1",
    )
    atomic_write_json(versions_dir(tmp_path, pid) / "v1.json", {
        "version_id": "v1",
        "schema": [
            {"name": "buyer_name", "type": "string", "description": "x", "required": False},
            {"name": "total_amount", "type": "number", "description": "x", "required": False},
        ],
        "global_notes": "",
        "model_id": "claude-sonnet-4-6",
        "params": {},
        "frozen_at": "2026-05-09T00:00:00Z",
    })
    for i in range(3):
        did = f"d_{i:012d}"
        _add_reviewed(tmp_path, pid, did, [{"buyer_name": "ACME"}])
        _add_prediction(tmp_path, pid, did, [{"buyer_name": "ACME"}])
    out = await readiness_check(tmp_path, pid)
    assert out["hard_pass"] is False
    assert any(c["key"] == "contract_diff_compat" and c["status"] == "fail" for c in out["checks"])
