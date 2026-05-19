"""HTTP coverage of ``POST /lab/projects/{slug}/prompts/{prompt_id}/activate``.

This is the id-flip mirror of the ``switch_active_prompt`` tool. The existing
``PUT .../prompts/active`` is a content edit (writes schema + notes for the
currently-active prompt); this route is the pure pointer flip.

M11 follow-up A — closes the CLI-symmetry gap surfaced by
``tests/unit/test_symmetry_invariant.py``.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project as _create
from app.tools.prompt import create_prompt as _create_prompt


client = TestClient(app)


def test_post_activate_prompt_switches_and_get_reflects(workspace: Path) -> None:
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    new_id = asyncio.run(_create_prompt(workspace, pid, label="trial"))

    # Sanity: default baseline prompt is active before the flip.
    before = client.get(f"/lab/projects/{pid}/prompts/active").json()
    assert before["prompt_id"] == "pr_baseline"

    r = client.post(f"/lab/projects/{pid}/prompts/{new_id}/activate")
    assert r.status_code == 200, r.text
    blob = r.json()
    assert blob["prompt_id"] == new_id
    assert blob["label"] == "trial"

    # Persisted: a fresh GET returns the same active prompt.
    after = client.get(f"/lab/projects/{pid}/prompts/active").json()
    assert after["prompt_id"] == new_id


def test_post_activate_prompt_unknown_id_returns_404(workspace: Path) -> None:
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    r = client.post(f"/lab/projects/{pid}/prompts/pr_nope_never_existed/activate")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "prompt_not_found"

    # Active prompt is unchanged.
    blob = client.get(f"/lab/projects/{pid}/prompts/active").json()
    assert blob["prompt_id"] == "pr_baseline"


def test_post_activate_prompt_idempotent(workspace: Path) -> None:
    """Re-activating the currently-active prompt is a no-op (returns 200 with
    the same blob)."""
    pid = asyncio.run(_create(workspace, name="t"))["slug"]

    # pr_baseline is already active; re-activate it.
    r = client.post(f"/lab/projects/{pid}/prompts/pr_baseline/activate")
    assert r.status_code == 200, r.text
    assert r.json()["prompt_id"] == "pr_baseline"

    # Still active after the no-op.
    blob = client.get(f"/lab/projects/{pid}/prompts/active").json()
    assert blob["prompt_id"] == "pr_baseline"


def test_post_activate_prompt_unknown_project_404(workspace: Path) -> None:
    r = client.post("/lab/projects/p_does_not_exist/prompts/pr_baseline/activate")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"
