"""HTTP twin of `forget_memory` — the headless half of memory consolidation.

The AI-native symmetry rule says a CLI client must be able to do anything the
in-session agent can. Reading/writing notes already rides on ws_read/ws_write;
retiring one is the operation that needs a verb, so it needs a route.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.memory import project_memory_dir, team_memory_dir


def _seed(directory: Path, slug: str, hook: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.md").write_text("学到于 2026-06-01\nfact", encoding="utf-8")
    index = directory / "MEMORY.md"
    prior = index.read_text(encoding="utf-8") if index.is_file() else ""
    index.write_text(f"{prior}- [{slug}]({slug}.md) — {hook}\n", encoding="utf-8")


def test_delete_project_note(workspace: Path) -> None:
    d = project_memory_dir(workspace, "us-invoice")
    _seed(d, "old-model", "用 gemini-flash")
    _seed(d, "keep-me", "交付物进 _export/")

    r = TestClient(app).delete("/lab/projects/us-invoice/memory/old-model")
    assert r.status_code == 200
    body = r.json()
    assert body["forgotten"] and body["deindexed"] and body["trashed_to"]

    assert not (d / "old-model.md").exists()
    index = (d / "MEMORY.md").read_text(encoding="utf-8")
    assert "old-model.md" not in index and "keep-me.md" in index


def test_delete_team_note(workspace: Path) -> None:
    _seed(team_memory_dir(workspace), "cadence", "该客户月底才对账")
    r = TestClient(app).delete("/lab/memory/cadence")
    assert r.status_code == 200 and r.json()["scope"] == "team"


def test_unknown_note_404s(workspace: Path) -> None:
    _seed(project_memory_dir(workspace, "us-invoice"), "a", "hook")
    r = TestClient(app).delete("/lab/projects/us-invoice/memory/never-existed")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "memory_note_not_found"


def test_the_index_itself_is_refused(workspace: Path) -> None:
    """400, not 404 — the note exists; retiring it is what's disallowed."""
    _seed(project_memory_dir(workspace, "us-invoice"), "a", "hook")
    r = TestClient(app).delete("/lab/projects/us-invoice/memory/MEMORY.md")
    assert r.status_code == 400
    assert (project_memory_dir(workspace, "us-invoice") / "MEMORY.md").is_file()


def test_one_projects_route_cannot_reach_anothers_notes(workspace: Path) -> None:
    _seed(project_memory_dir(workspace, "other"), "secret", "别的项目")
    r = TestClient(app).delete("/lab/projects/us-invoice/memory/secret")
    assert r.status_code == 404
    assert (project_memory_dir(workspace, "other") / "secret.md").is_file()
