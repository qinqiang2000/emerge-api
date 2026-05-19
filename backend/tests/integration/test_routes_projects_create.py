"""HTTP coverage for `POST /lab/projects` (M11 Phase B T8).

The route is a thin HTTP wrapper around the `create_project` tool's module
function. We assert the shape of the response, the on-disk side-effect
(project.json materialises with the right pid/slug/name), and the body
validation path (empty name → 400)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.paths import project_json_path


def test_create_project_route_returns_slug_pid_name(workspace: Path) -> None:
    """Happy path: POST `{name}` → 200 with `{slug, project_id, name}` and a
    materialised `project.json` on disk."""
    client = TestClient(app)
    r = client.post("/lab/projects", json={"name": "us-invoice"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "us-invoice"
    # Slug derived from `name` (matches `derive_slug`'s casing rule —
    # already lowercase here, but the contract is "echoed back as `name`").
    assert body["slug"] == "us-invoice"
    assert body["project_id"].startswith("p_")

    # Side-effect: project.json on disk carries both handles.
    pj = project_json_path(workspace, body["slug"])
    assert pj.exists()
    blob = json.loads(pj.read_text())
    assert blob["name"] == "us-invoice"
    assert blob["project_id"] == body["project_id"]


def test_create_project_route_rejects_empty_name() -> None:
    """Validation: blank / whitespace-only name → 400 with a sensible code."""
    client = TestClient(app)
    r = client.post("/lab/projects", json={"name": "   "})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "invalid_name"


def test_create_project_route_handles_unicode_name(workspace: Path) -> None:
    """CJK names round-trip — slug stays Unicode (matches `derive_slug`'s
    unicode-preserving rule) and project.json carries the original display
    name."""
    client = TestClient(app)
    r = client.post("/lab/projects", json={"name": "美国发票"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "美国发票"
    # `derive_slug` only lowercases ASCII; CJK round-trips unchanged.
    assert body["slug"] == "美国发票"
    assert (workspace / body["slug"] / "project.json").exists()
