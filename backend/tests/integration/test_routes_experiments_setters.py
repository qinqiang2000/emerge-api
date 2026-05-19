"""M11 T12 — lab HTTP setters for experiments (create / eval / promote).

Mirror surface: each route delegates to the same module function the
corresponding `@tool` wraps. Tests exercise happy paths + the structured
error envelopes (404 / 409) — wire-level checks only; the underlying
business logic is covered by `tests/unit/test_tool_experiment.py`.
"""
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
    reviewed_dir,
    reviewed_path,
)


def _now() -> str:
    return "2026-05-19T00:00:00+00:00"


def _seed_project_with_axes(workspace: Path, slug: str) -> None:
    """One project with one active prompt + one active model."""
    pdir = workspace / slug
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, slug), {
        "project_id": slug, "name": "Test", "created_at": _now(),
        "active_prompt_id": "pr_baseline", "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, slug, "pr_baseline"), {
        "prompt_id": "pr_baseline", "label": "Baseline",
        "schema": [
            {"name": "supplier", "type": "string", "description": "d", "required": False},
        ],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, slug, "m_default"), {
        "model_id": "m_default", "label": "Default",
        "provider": "google", "provider_model_id": "gemini-2.5-flash",
        "params": {}, "created_at": _now(),
    })


def _seed_doc(workspace: Path, slug: str, filename: str) -> None:
    """Minimal PNG + sidecar so extract_with_experiment can resolve the doc."""
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, slug, filename).write_bytes(
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08'
        b'\x08\x06\x00\x00\x00\xc4\x0f\xbe\x8b\x00\x00\x00\x0cIDATx\x9cc\xf8'
        b'\xcf\xc0\x00\x00\x00\x03\x00\x01]Z9o\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    meta_p = doc_meta_path(workspace, slug, filename)
    meta_p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_p, {
        "filename": filename, "original_name": filename, "ext": "png",
        "sha256": "stub", "page_count": 1, "uploaded_at": _now(),
    })


def _seed_reviewed(workspace: Path, slug: str, filename: str) -> None:
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(reviewed_path(workspace, slug, filename), {
        "entities": [{"supplier": "ACME"}],
        "source": "manual",
    })


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/experiments — create_experiment
# ---------------------------------------------------------------------------


def test_post_experiments_creates_with_defaults(client: TestClient, tmp_path: Path) -> None:
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    r = client.post(f"/lab/projects/{slug}/experiments", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["experiment_id"].startswith("ex_")
    assert body["prompt_id"] == "pr_baseline"
    assert body["model_id"] == "m_default"
    assert body["status"] == "draft"


def test_post_experiments_is_upsert_by_axes(client: TestClient, tmp_path: Path) -> None:
    """Same (prompt, model) pair → same experiment_id (no duplicate)."""
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    r1 = client.post(f"/lab/projects/{slug}/experiments", json={})
    r2 = client.post(f"/lab/projects/{slug}/experiments", json={})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["experiment_id"] == r2.json()["experiment_id"]


def test_post_experiments_404_on_missing_project(client: TestClient) -> None:
    r = client.post("/lab/projects/p_nonexistent12/experiments", json={})
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/experiments/{eid}/eval — run_experiment_eval
# ---------------------------------------------------------------------------


def test_post_eval_runs_and_returns_score(
    client: TestClient, tmp_path: Path, monkeypatch,
) -> None:
    """Happy path: reviewed/ has 1 doc, stub provider returns the same
    entities, eval returns score=1.0 and coverage=1."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    filename = "sample.png"
    _seed_doc(tmp_path, slug, filename)
    _seed_reviewed(tmp_path, slug, filename)
    eid = asyncio.run(create_experiment(tmp_path, slug))

    stub = AsyncMock(spec=Provider)
    stub.extract.return_value = ProviderResult(
        raw_json={"entities": [{"supplier": "ACME"}]},
        model_id="stub", input_tokens=0, output_tokens=0,
    )
    import app.api.routes.experiments as exp_route
    monkeypatch.setattr(exp_route, "get_provider_for_model", lambda *_a, **_k: stub)

    r = client.post(f"/lab/projects/{slug}/experiments/{eid}/eval", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["score"] == 1.0
    assert body["coverage"] == 1
    assert filename in body["per_doc"]


def test_post_eval_400_when_no_reviewed(
    client: TestClient, tmp_path: Path, monkeypatch,
) -> None:
    """No reviewed/ docs → eval has nothing to score against → 400."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    eid = asyncio.run(create_experiment(tmp_path, slug))

    # Provider won't even be called, but patch defensively so a real factory
    # doesn't try to talk to Google.
    stub = AsyncMock(spec=Provider)
    import app.api.routes.experiments as exp_route
    monkeypatch.setattr(exp_route, "get_provider_for_model", lambda *_a, **_k: stub)

    r = client.post(f"/lab/projects/{slug}/experiments/{eid}/eval", json={})
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "no_reviewed_docs"


def test_post_eval_404_on_missing_experiment(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    r = client.post(
        f"/lab/projects/{slug}/experiments/ex_doesnotexist/eval", json={},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "experiment_not_found"


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/experiments/{eid}/promote — promote / archive
# ---------------------------------------------------------------------------


def test_post_promote_to_active_flips_project(
    client: TestClient, tmp_path: Path,
) -> None:
    """to='active' switches active_prompt_id + active_model_id and marks
    experiment status='promoted'."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    # variant prompt so the flip is observable
    atomic_write_json(prompt_path(tmp_path, slug, "pr_v2"), {
        "prompt_id": "pr_v2", "label": "v2",
        "schema": [{"name": "x", "type": "string", "description": "x", "required": False}],
        "global_notes": "", "derived_from": None,
        "created_at": _now(), "updated_at": _now(),
    })
    eid = asyncio.run(create_experiment(tmp_path, slug, prompt_id="pr_v2"))

    r = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote",
        json={"to": "active"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    blob = json.loads(project_json_path(tmp_path, slug).read_text())
    assert blob["active_prompt_id"] == "pr_v2"
    meta = json.loads(experiment_meta_path(tmp_path, slug, eid).read_text())
    assert meta["status"] == "promoted"


def test_post_promote_to_archived_marks_archived(
    client: TestClient, tmp_path: Path,
) -> None:
    """to='archived' moves status without touching project axes."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    eid = asyncio.run(create_experiment(tmp_path, slug))

    r = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote",
        json={"to": "archived"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    meta = json.loads(experiment_meta_path(tmp_path, slug, eid).read_text())
    assert meta["status"] == "archived"
    # active axes unchanged
    blob = json.loads(project_json_path(tmp_path, slug).read_text())
    assert blob["active_prompt_id"] == "pr_baseline"


def test_post_promote_default_target_is_active(
    client: TestClient, tmp_path: Path,
) -> None:
    """Empty body defaults `to='active'` — matches the pydantic default."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    eid = asyncio.run(create_experiment(tmp_path, slug))

    r = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote", json={},
    )
    assert r.status_code == 200
    meta = json.loads(experiment_meta_path(tmp_path, slug, eid).read_text())
    assert meta["status"] == "promoted"


def test_post_promote_404_on_missing_experiment(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    r = client.post(
        f"/lab/projects/{slug}/experiments/ex_doesnotexist/promote",
        json={"to": "active"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "experiment_not_found"


def test_post_promote_archived_blocked_on_promoted(
    client: TestClient, tmp_path: Path,
) -> None:
    """audit-trail: cannot archive a `promoted` experiment → 409."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    eid = asyncio.run(create_experiment(tmp_path, slug))
    # First promote to active.
    r = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote",
        json={"to": "active"},
    )
    assert r.status_code == 200
    # Now try to archive — should be blocked.
    r2 = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote",
        json={"to": "archived"},
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "experiment_promoted"


def test_post_promote_invalid_to_value_422(
    client: TestClient, tmp_path: Path,
) -> None:
    """Pydantic Literal['active','archived'] rejects junk values."""
    from app.tools.experiment import create_experiment
    slug = "p_test12345678"
    _seed_project_with_axes(tmp_path, slug)
    eid = asyncio.run(create_experiment(tmp_path, slug))

    r = client.post(
        f"/lab/projects/{slug}/experiments/{eid}/promote",
        json={"to": "draft"},
    )
    assert r.status_code == 422
