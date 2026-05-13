from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.provider.base import Provider, ProviderResult
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    docs_dir,
    experiment_meta_path,
    model_path,
    project_json_path,
    prompt_path,
)


def _now() -> str:
    return "2026-05-13T00:00:00+00:00"


def _seed_project_with_axes(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "project_id": pid, "name": "Test", "created_at": _now(),
        "active_prompt_id": "pr_baseline", "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "Baseline",
        "schema": [{"name": "supplier", "type": "string", "description": "d", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, pid, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {}, "created_at": _now(),
    })


def _seed_doc(workspace: Path, pid: str, did: str) -> None:
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, did, "png").write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08'
        b'\x08\x06\x00\x00\x00\xc4\x0f\xbe\x8b\x00\x00\x00\x0cIDATx\x9cc\xf8'
        b'\xcf\xc0\x00\x00\x00\x03\x00\x01]Z9o\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    atomic_write_json(doc_meta_path(workspace, pid, did), {
        "doc_id": did, "filename": f"{did}.png", "ext": "png",
        "size_bytes": 70, "uploaded_at": _now(),
    })


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def test_list_experiments_empty(client: TestClient, tmp_path: Path) -> None:
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    r = client.get(f"/lab/projects/{pid}/experiments")
    assert r.status_code == 200
    assert r.json() == []


def test_list_experiments_after_create(client: TestClient, tmp_path: Path) -> None:
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    asyncio.run(create_experiment(tmp_path, pid))
    r = client.get(f"/lab/projects/{pid}/experiments")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    # Label derives from prompt + model labels in the seeded fixture
    assert rows[0]["label"] == "Baseline × Default"
    assert rows[0]["status"] == "draft"


def test_get_experiment_meta(client: TestClient, tmp_path: Path) -> None:
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    eid = asyncio.run(create_experiment(tmp_path, pid))
    r = client.get(f"/lab/projects/{pid}/experiments/{eid}")
    assert r.status_code == 200
    body = r.json()
    assert body["experiment_id"] == eid
    assert body["prompt_id"] == "pr_baseline"


def test_get_prediction_404_when_not_run(client: TestClient, tmp_path: Path) -> None:
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    eid = asyncio.run(create_experiment(tmp_path, pid))
    did = "d_doc000000000"
    r = client.get(f"/lab/projects/{pid}/experiments/{eid}/predictions/{did}")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "experiment_prediction_not_found"


def test_run_prediction_endpoint_writes_and_returns(
    client: TestClient, tmp_path: Path, monkeypatch,
) -> None:
    """POST .../predictions/{doc_id} runs extract_with_experiment.
    Monkeypatch get_provider_for_model so the route doesn't hit a real LLM."""
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    did = "d_doc000000000"
    _seed_doc(tmp_path, pid, did)
    eid = asyncio.run(create_experiment(tmp_path, pid))

    # build a stub provider for the route to use
    stub = AsyncMock(spec=Provider)
    stub.extract.return_value = ProviderResult(
        raw_json={"entities": [{"supplier": "ACME"}]},
        model_id="stub", input_tokens=0, output_tokens=0,
    )
    # Patch get_provider_for_model on the route module directly so the import
    # the route already holds is replaced.
    import app.api.routes.experiments as exp_route
    monkeypatch.setattr(exp_route, "get_provider_for_model", lambda *_a, **_k: stub)

    r = client.post(f"/lab/projects/{pid}/experiments/{eid}/predictions/{did}")
    assert r.status_code == 200
    body = r.json()
    assert body["entities"][0]["supplier"] == "ACME"

    # subsequent GET now returns 200
    r2 = client.get(f"/lab/projects/{pid}/experiments/{eid}/predictions/{did}")
    assert r2.status_code == 200


def test_invalid_project_id_rejected(client: TestClient, tmp_path: Path) -> None:
    r = client.get("/lab/projects/..%2Fattacker/experiments")
    assert r.status_code in (400, 404, 422)


def test_invalid_doc_id_rejected_on_prediction_routes(
    client: TestClient, tmp_path: Path,
) -> None:
    """doc_id must match d_[a-z0-9]{12}; reject path-traversal attempts."""
    from app.tools.experiment import create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    eid = asyncio.run(create_experiment(tmp_path, pid))

    # malformed doc_id with literal "/" — FastAPI rejects via 404 on routing
    r1 = client.get(f"/lab/projects/{pid}/experiments/{eid}/predictions/../../etc/passwd")
    assert r1.status_code in (400, 404, 422)

    # malformed doc_id matching the path component but not the d_ pattern —
    # safe_doc_id() must reject this
    r2 = client.get(f"/lab/projects/{pid}/experiments/{eid}/predictions/notadocid")
    assert r2.status_code in (400, 422)

    r3 = client.post(f"/lab/projects/{pid}/experiments/{eid}/predictions/notadocid")
    assert r3.status_code in (400, 422)


def test_list_experiments_include_archived_query_param(
    client: TestClient, tmp_path: Path,
) -> None:
    """Default response excludes archived; ?include_archived=true returns them."""
    from app.tools.experiment import archive_experiment, create_experiment
    pid = "p_test12345678"
    _seed_project_with_axes(tmp_path, pid)
    # Two distinct axes pairs — upsert dedups same-axes, so test needs different pairs
    atomic_write_json(prompt_path(tmp_path, pid, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    e1 = asyncio.run(create_experiment(tmp_path, pid))
    e2 = asyncio.run(create_experiment(tmp_path, pid, prompt_id="pr_v2"))
    asyncio.run(archive_experiment(tmp_path, pid, e2))

    # default — only the live experiment
    r = client.get(f"/lab/projects/{pid}/experiments")
    assert r.status_code == 200
    assert [row["experiment_id"] for row in r.json()] == [e1]

    # with the query param — both
    r2 = client.get(f"/lab/projects/{pid}/experiments?include_archived=true")
    assert r2.status_code == 200
    assert {row["experiment_id"] for row in r2.json()} == {e1, e2}
