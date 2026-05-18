"""HTTP routes for the Pro Labeler — POST /pre_label, POST /labeler_model,
GET /pending/{filename}. Symmetry mirror of the MCP tools (M10)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    pending_reviewed_dir,
    pending_reviewed_path,
    project_json_path,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    # Make sure no env labeler bleeds in.
    monkeypatch.delenv("EMERGE_DEFAULT_LABELER_MODEL", raising=False)
    return TestClient(app)


def _create_project(tmp_path: Path) -> str:
    return asyncio.run(create_project(tmp_path, name="x"))["slug"]


def test_pre_label_route_returns_400_when_unconfigured(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = _create_project(tmp_path)
    r = client.post(f"/lab/projects/{slug}/pre_label", json={})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["error_code"] == "labeler_model_not_configured"


def test_labeler_config_route_reports_unconfigured(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = _create_project(tmp_path)
    r = client.get(f"/lab/projects/{slug}/labeler_config")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "override": None,
        "env_default": None,
        "resolved": None,
        "source": "unconfigured",
    }


def test_labeler_config_route_reports_env_default(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMERGE_DEFAULT_LABELER_MODEL", "gemini-pro-latest")
    slug = _create_project(tmp_path)
    r = client.get(f"/lab/projects/{slug}/labeler_config")
    assert r.status_code == 200
    assert r.json() == {
        "override": None,
        "env_default": "gemini-pro-latest",
        "resolved": "gemini-pro-latest",
        "source": "env_default",
    }


def test_labeler_config_route_reports_override(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = _create_project(tmp_path)
    client.post(
        f"/lab/projects/{slug}/labeler_model",
        json={"model_id": "claude-opus-4-1"},
    )
    r = client.get(f"/lab/projects/{slug}/labeler_config")
    assert r.status_code == 200
    body = r.json()
    assert body["override"] == "claude-opus-4-1"
    assert body["resolved"] == "claude-opus-4-1"
    assert body["source"] == "override"


def test_pre_label_route_404_on_unknown_project(client: TestClient) -> None:
    r = client.post("/lab/projects/p_doesnotexist1/pre_label", json={})
    assert r.status_code == 404


def test_post_labeler_model_persists(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = _create_project(tmp_path)
    r = client.post(
        f"/lab/projects/{slug}/labeler_model",
        json={"model_id": "gemini-pro-latest"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    blob = json.loads(project_json_path(tmp_path, slug).read_text())
    assert blob["labeler_model"] == "gemini-pro-latest"


def test_get_pending_404_when_missing(
    client: TestClient, tmp_path: Path,
) -> None:
    slug = _create_project(tmp_path)
    r = client.get(f"/lab/projects/{slug}/pending/missing.pdf")
    assert r.status_code == 404


def test_get_pending_returns_draft(client: TestClient, tmp_path: Path) -> None:
    slug = _create_project(tmp_path)
    pending_reviewed_dir(tmp_path, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        pending_reviewed_path(tmp_path, slug, "inv-1.pdf"),
        {
            "entities": [{"invoice_no": "INV-1"}],
            "labeler_model": "gemini-pro-latest",
            "created_at": "2026-05-17T00:00:00+00:00",
        },
    )
    r = client.get(f"/lab/projects/{slug}/pending/inv-1.pdf")
    assert r.status_code == 200
    body = r.json()
    assert body["entities"][0]["invoice_no"] == "INV-1"
    assert body["labeler_model"] == "gemini-pro-latest"
