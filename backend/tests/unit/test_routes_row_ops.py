"""HTTP twins of the spine's row actions (⋮ → Rename / Delete).

These routes are what the sidebar calls, but they are not UI-only: each has a
tool or Bash-reachable counterpart, and a CLI client drives the same verbs.
What's pinned here is the part a UI can't be trusted to enforce — the refusals
(active prompt / active model / promoted experiment / project with a live
turn) and the "delete moves to `_trash/`, never unlinks" rule.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workspace.paths import trash_root


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def _project(ws: Path, name: str = "t") -> str:
    from app.tools.projects import create_project

    return asyncio.run(create_project(ws, name=name))["slug"]


def _trash_entries(ws: Path) -> list[str]:
    root = trash_root(ws)
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


# ── project ────────────────────────────────────────────────────────────────

def test_rename_project_moves_folder_and_returns_new_slug(client: TestClient, tmp_path: Path) -> None:
    slug = _project(tmp_path, "old name")
    r = client.post(f"/lab/projects/{slug}/rename", json={"name": "new name"})
    assert r.status_code == 200
    new_slug = r.json()["slug"]
    assert new_slug != slug
    assert (tmp_path / new_slug / "project.json").exists()
    assert not (tmp_path / slug).exists()
    # The display name landed too — slug and name stay locked together.
    assert client.get(f"/lab/projects/{new_slug}").json()["name"] == "new name"
    # Old handle is gone, which is why the route returns the new one.
    assert client.get(f"/lab/projects/{slug}").status_code == 404


def test_rename_project_refuses_while_a_turn_runs(client: TestClient, tmp_path: Path) -> None:
    # Renaming os.rename's the project dir; a running agent's cwd IS that dir.
    from app.api.routes.turns import get_registry

    slug = _project(tmp_path)
    monkeyed = get_registry()
    original = monkeyed.active_slugs
    monkeyed.active_slugs = lambda _ws: {slug}  # type: ignore[method-assign]
    try:
        r = client.post(f"/lab/projects/{slug}/rename", json={"name": "renamed"})
    finally:
        monkeyed.active_slugs = original  # type: ignore[method-assign]
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "project_busy"
    assert (tmp_path / slug).exists()


def test_rename_project_rejects_empty_and_missing(client: TestClient, tmp_path: Path) -> None:
    slug = _project(tmp_path)
    assert client.post(f"/lab/projects/{slug}/rename", json={"name": "  "}).status_code == 400
    assert client.post(f"/lab/projects/{slug}/rename", json={}).status_code == 400
    assert client.post("/lab/projects/ghost/rename", json={"name": "x"}).status_code == 404


# ── prompts ────────────────────────────────────────────────────────────────

def test_rename_prompt_changes_label_only(client: TestClient, tmp_path: Path) -> None:
    from app.tools.prompt import create_prompt

    slug = _project(tmp_path)
    pid = asyncio.run(create_prompt(tmp_path, slug, label="trial"))
    before = client.get(f"/lab/projects/{slug}/prompts/{pid}").json()

    r = client.post(f"/lab/projects/{slug}/prompts/{pid}/rename", json={"label": "v2 wording"})
    assert r.status_code == 200

    after = client.get(f"/lab/projects/{slug}/prompts/{pid}").json()
    assert after["label"] == "v2 wording"
    # A rename is not a new prompt version — experiments pinned to `version`
    # must keep resolving to the same snapshot.
    assert after["version"] == before["version"]
    assert after["schema"] == before["schema"]
    assert after["global_notes"] == before["global_notes"]

    assert client.post(f"/lab/projects/{slug}/prompts/{pid}/rename", json={"label": " "}).status_code == 400
    assert client.post(f"/lab/projects/{slug}/prompts/ghost/rename", json={"label": "x"}).status_code == 404


def test_delete_prompt_trashes_and_refuses_the_active_one(client: TestClient, tmp_path: Path) -> None:
    from app.tools.prompt import create_prompt

    slug = _project(tmp_path)
    pid = asyncio.run(create_prompt(tmp_path, slug, label="trial"))
    active = next(p["prompt_id"] for p in client.get(f"/lab/projects/{slug}/prompts").json() if p["is_active"])

    r = client.delete(f"/lab/projects/{slug}/prompts/{active}")
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "prompt_in_use"

    assert client.delete(f"/lab/projects/{slug}/prompts/{pid}").status_code == 200
    assert client.get(f"/lab/projects/{slug}/prompts/{pid}").status_code == 404
    # Hand-tuned work: it moved to trash rather than being unlinked.
    assert any(e.endswith(f"prompt-{pid}") for e in _trash_entries(tmp_path))
    assert client.delete(f"/lab/projects/{slug}/prompts/{pid}").status_code == 404


def test_delete_prompt_refuses_when_an_experiment_points_at_it(client: TestClient, tmp_path: Path) -> None:
    from app.tools.experiment import create_experiment
    from app.tools.model import create_model
    from app.tools.prompt import create_prompt

    slug = _project(tmp_path)
    pid = asyncio.run(create_prompt(tmp_path, slug, label="trial"))
    mid = asyncio.run(create_model(
        tmp_path, slug, label="m", provider="google", provider_model_id="gemini-2.5-flash",
    ))
    asyncio.run(create_experiment(tmp_path, slug, prompt_id=pid, model_id=mid))

    r = client.delete(f"/lab/projects/{slug}/prompts/{pid}")
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "prompt_in_use"


# ── models ─────────────────────────────────────────────────────────────────

def test_rename_model_changes_label_not_provider_id(client: TestClient, tmp_path: Path) -> None:
    from app.tools.model import create_model

    slug = _project(tmp_path)
    mid = asyncio.run(create_model(
        tmp_path, slug, label="", provider="google", provider_model_id="gemini-2.5-flash",
    ))
    r = client.post(f"/lab/projects/{slug}/models/{mid}/rename", json={"label": "flash (no thinking)"})
    assert r.status_code == 200

    blob = client.get(f"/lab/projects/{slug}/models/{mid}").json()
    assert blob["label"] == "flash (no thinking)"
    # The id the provider API answers to is never a nickname.
    assert blob["provider_model_id"] == "gemini-2.5-flash"

    assert client.post(f"/lab/projects/{slug}/models/{mid}/rename", json={"label": ""}).status_code == 400
    assert client.post(f"/lab/projects/{slug}/models/ghost/rename", json={"label": "x"}).status_code == 404


def test_delete_model_trashes_and_refuses_the_active_one(client: TestClient, tmp_path: Path) -> None:
    from app.tools.model import create_model, switch_active_model

    slug = _project(tmp_path)
    keep = asyncio.run(create_model(
        tmp_path, slug, label="keep", provider="google", provider_model_id="gemini-2.5-flash",
    ))
    drop = asyncio.run(create_model(
        tmp_path, slug, label="drop", provider="google", provider_model_id="gemini-2.5-pro",
    ))
    asyncio.run(switch_active_model(tmp_path, slug, keep))

    r = client.delete(f"/lab/projects/{slug}/models/{keep}")
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "model_in_use"

    assert client.delete(f"/lab/projects/{slug}/models/{drop}").status_code == 200
    assert client.get(f"/lab/projects/{slug}/models/{drop}").status_code == 404
    # base_url / api_key_env are settings the user looked up once — recoverable.
    assert any(drop in e for e in _trash_entries(tmp_path))


# ── experiments ────────────────────────────────────────────────────────────

def _experiment(ws: Path, slug: str) -> str:
    from app.tools.experiment import create_experiment
    from app.tools.model import create_model
    from app.tools.prompt import create_prompt

    pid = asyncio.run(create_prompt(ws, slug, label="trial"))
    mid = asyncio.run(create_model(
        ws, slug, label="m", provider="google", provider_model_id="gemini-2.5-flash",
    ))
    return asyncio.run(create_experiment(ws, slug, prompt_id=pid, model_id=mid))


def test_rename_experiment_keeps_its_pinned_axes(client: TestClient, tmp_path: Path) -> None:
    slug = _project(tmp_path)
    eid = _experiment(tmp_path, slug)
    before = client.get(f"/lab/projects/{slug}/experiments/{eid}").json()

    r = client.post(f"/lab/projects/{slug}/experiments/{eid}/rename", json={"label": "the good one"})
    assert r.status_code == 200

    after = client.get(f"/lab/projects/{slug}/experiments/{eid}").json()
    assert after["label"] == "the good one"
    # Renaming replaces the caption, never what the results actually ran on.
    for axis in ("prompt_id", "prompt_version", "model_id"):
        assert after[axis] == before[axis]

    assert client.post(f"/lab/projects/{slug}/experiments/{eid}/rename", json={"label": ""}).status_code == 400
    assert client.post(f"/lab/projects/{slug}/experiments/ghost/rename", json={"label": "x"}).status_code == 404


def test_delete_experiment_trashes_and_refuses_a_promoted_one(client: TestClient, tmp_path: Path) -> None:
    from app.tools.experiment import promote_experiment

    slug = _project(tmp_path)
    eid = _experiment(tmp_path, slug)

    assert client.delete(f"/lab/projects/{slug}/experiments/{eid}").status_code == 200
    assert any(eid in e for e in _trash_entries(tmp_path))
    assert client.delete(f"/lab/projects/{slug}/experiments/{eid}").status_code == 404

    other = _experiment(tmp_path, slug)
    asyncio.run(promote_experiment(tmp_path, slug, other))
    r = client.delete(f"/lab/projects/{slug}/experiments/{other}")
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "experiment_promoted"
