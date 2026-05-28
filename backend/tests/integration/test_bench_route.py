"""T3 — Bench HTTP route ↔ MCP tool dual-form integration tests.

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T3.

Thin-delegate route: `GET /lab/projects/{slug}/bench` → `compute_bench`.
Both happy path (200 with expected shape) and the structured error path
(404 when the project doesn't exist) are covered; safe_slug rejects
path-traversal at the routing/handler boundary before any filesystem
read so an attacker can't enumerate sibling folders via the bench
surface.

Underlying aggregator logic is exhaustively unit-tested in
`tests/unit/test_bench_service.py`; this file only exercises the
wire-level contract (status + shape + safety gate).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    model_path,
    project_json_path,
    prompt_path,
    reviewed_dir,
    reviewed_path,
)


def _now() -> str:
    return "2026-05-28T00:00:00+00:00"


def _seed_project_with_axes(workspace: Path, slug: str) -> None:
    """Minimal seed: project + active prompt + active model. Mirrors
    the helper used by the service unit tests so bench output is
    shaped exactly like the leaderboard expects."""
    pdir = workspace / slug
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, slug), {
        "project_id": "p_test12345678",
        "name": "Test",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
    })
    atomic_write_json(prompt_path(workspace, slug, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": [
            {"name": "supplier", "type": "string", "description": "d", "required": False},
        ],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    atomic_write_json(model_path(workspace, slug, "m_default"), {
        "model_id": "m_default",
        "label": "Default",
        "provider": "google",
        "provider_model_id": "gemini-2.5-flash",
        "params": {},
        "created_at": _now(),
    })


def _seed_reviewed(workspace: Path, slug: str, filename: str) -> None:
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(reviewed_path(workspace, slug, filename), {
        "entities": [{"supplier": "ACME"}],
        "source": "manual",
    })


def test_get_bench_200(workspace: Path) -> None:
    """Happy path — seeded project returns 200 with the expected
    BenchResponse keys. Doesn't verify deep shape (unit tests cover
    that); only locks in the wire contract: top-level dict with the
    six top-level keys the frontend reads."""
    slug = "bench-happy"
    _seed_project_with_axes(workspace, slug)
    _seed_reviewed(workspace, slug, "doc1.pdf")

    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/bench")
    assert r.status_code == 200, r.text
    body = r.json()
    # Plan §"数据契约" — six required top-level keys.
    for key in ("rows", "prompts", "models", "fields", "sample_filenames", "headline"):
        assert key in body, f"missing top-level key {key!r} in {body!r}"
    # Empty-but-seeded shape sanity — axes carry the seeded prompt/model.
    assert any(p["id"] == "pr_baseline" and p["is_active"] for p in body["prompts"])
    assert any(m["id"] == "m_default" and m["is_active"] for m in body["models"])
    # No experiments + no baseline eval → empty rows. Reviewed doc seeds the
    # sample header set.
    assert body["rows"] == []
    assert body["sample_filenames"] == ["doc1.pdf.json"]


def test_get_bench_404_when_project_missing() -> None:
    """A valid-shape slug that has no project.json gets a 404 with
    the canonical `project_not_found` error_code. Mirrors the shape
    used by experiments / publish / schema routes."""
    client = TestClient(app)
    r = client.get("/lab/projects/no-such-bench-project/bench")
    assert r.status_code == 404
    detail = r.json()["detail"]
    # error_code envelope matches the rest of the lab surface
    if isinstance(detail, dict):
        assert detail.get("error_code") == "project_not_found"
    else:
        assert detail == "project_not_found"


def test_get_bench_rejects_path_traversal() -> None:
    """`safe_slug` rejects slug values that would traverse out of the
    workspace root or contain control chars. The handler must reject
    *before* touching the filesystem so an attacker can't probe sibling
    folders. Two flavours: encoded `..` slashes (collapsed by routing
    or 404'd), and a NUL byte (reaches the handler as a literal segment
    and is rejected by safe_slug with 400 + 'invalid slug')."""
    client = TestClient(app)
    # NUL byte segment — safe_slug rejects with 400.
    r = client.get("/lab/projects/bad%00ctrl/bench")
    assert r.status_code == 400, r.text
    assert "invalid slug" in r.text

    # Traversal — FastAPI may normalise `..` segments at the routing
    # layer before they reach the handler; either way, no successful
    # 200 against `..` is the bar we have to clear.
    r2 = client.get("/lab/projects/../bench")
    assert r2.status_code in {400, 404, 405}, r2.text
