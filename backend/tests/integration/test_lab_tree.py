"""Project-tree browsing endpoint (`/lab/projects/{pid}/tree`) — backs the
composer `@` mention picker.

Covers:
- root listing filters internal-only entries (chats / jobs / metrics / etc.)
  while exposing `docs/`, `versions/`, `reviewed/`, `schema.json`.
- drill into `docs/` lists real on-disk filenames.
- drill into `versions/` exposes `v*.json` and hides `_candidate/`.
- `..` traversal rejected (400).
- unknown dir 404'd.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_tree_root_filters_internal_entries(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    root = workspace / pid

    # Seed a mix of allowed + filtered entries so we exercise the allow-list.
    (root / "docs").mkdir(exist_ok=True)
    (root / "versions").mkdir(exist_ok=True)
    (root / "reviewed").mkdir(exist_ok=True)
    (root / "chats").mkdir(exist_ok=True)
    (root / "jobs").mkdir(exist_ok=True)
    (root / "experiments").mkdir(exist_ok=True)
    (root / "predictions").mkdir(exist_ok=True)
    (root / "prompts").mkdir(exist_ok=True)
    (root / "models").mkdir(exist_ok=True)
    (root / "metrics").mkdir(exist_ok=True)
    (root / ".hidden").mkdir(exist_ok=True)
    (root / "schema.json").write_text("[]")

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/tree")
    assert r.status_code == 200
    items = r.json()
    names = {it["name"] for it in items}

    # Visible: workspace artifacts the agent + user share a view on.
    assert "docs" in names
    assert "versions" in names
    assert "reviewed" in names
    assert "schema.json" in names

    # Hidden: internal-only state.
    assert "chats" not in names
    assert "jobs" not in names
    assert "experiments" not in names
    assert "predictions" not in names
    assert "prompts" not in names
    assert "models" not in names
    assert "metrics" not in names
    assert ".hidden" not in names
    assert "project.json" not in names

    # Sort invariant: directories first, then files, each block alphabetical.
    kinds = [it["kind"] for it in items]
    assert kinds == sorted(kinds, key=lambda k: 0 if k == "dir" else 1)


async def test_tree_drill_into_docs(workspace: Path) -> None:
    from app.tools.docs import upload_doc

    pid = await create_project(workspace, name="x")
    pdf = b"%PDF-1.4\n%%EOF\n"
    m1 = await upload_doc(workspace, pid, pdf, "invoice-jan.pdf")
    m2 = await upload_doc(workspace, pid, pdf, "2025VP00413.pdf")

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/tree", params={"dir": "docs"})
    assert r.status_code == 200
    items = r.json()
    names = {it["name"] for it in items}
    # Real filenames surface; sidecar `.meta/` filtered by the leading-dot rule.
    assert m1["filename"] in names
    assert m2["filename"] in names
    assert ".meta" not in names
    # All entries are files with paths under docs/.
    for it in items:
        assert it["kind"] == "file"
        assert it["path"].startswith("docs/")


async def test_tree_drill_into_versions_hides_candidate(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    vdir = workspace / pid / "versions"
    vdir.mkdir(exist_ok=True)
    (vdir / "v1.json").write_text(json.dumps({"fields": []}))
    (vdir / "v2.json").write_text(json.dumps({"fields": []}))
    (vdir / "_candidate").mkdir(exist_ok=True)
    (vdir / "_candidate" / "j_aaaaaaaaaaaa").mkdir(exist_ok=True)

    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/tree", params={"dir": "versions"})
    assert r.status_code == 200
    names = {it["name"] for it in r.json()}
    assert "v1.json" in names
    assert "v2.json" in names
    # Candidate state is transient — hidden.
    assert "_candidate" not in names


def test_tree_rejects_parent_traversal() -> None:
    # Just need a valid-shaped pid; the endpoint should 400 before any
    # filesystem touch on a bad `dir`.
    client = TestClient(app)
    for bad in ("..", "../etc", "docs/..", "docs/../..", "./docs", "/abs/path"):
        r = client.get("/lab/projects/p_aaaaaaaaaaaa/tree", params={"dir": bad})
        assert r.status_code == 400, f"expected 400 for dir={bad!r}, got {r.status_code}"


async def test_tree_unknown_dir_404(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/tree", params={"dir": "nope"})
    assert r.status_code == 404


def test_tree_bad_pid_400() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/tree")
    assert r.status_code == 400


def test_tree_unknown_project_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_aaaaaaaaaaaa/tree")
    assert r.status_code == 404
