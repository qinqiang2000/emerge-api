"""Orphan-project cleanup + create_project rollback tests.

Pins three contracts:
  1. cleanup_orphan_projects removes dirs missing project.json — but leaves
     real projects, sentinel dirs (`_staging`, `_orphans`), and hidden
     dotfiles alone.
  2. create_project rolls back the partial dir if any post-mkdir step
     raises, so failures never leave un-listable debris.
  3. create_project happy path still leaves a complete project (regression
     guard against the rollback path swallowing real success).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tools.projects import create_project
from app.workspace.orphans import cleanup_orphan_projects


# ── cleanup_orphan_projects ────────────────────────────────────────────────


def test_cleanup_removes_dirs_without_project_json(workspace: Path) -> None:
    orphan = workspace / "untitled-260514-152406"
    orphan.mkdir()
    (orphan / "chats").mkdir()  # half-written state
    assert cleanup_orphan_projects(workspace) == 1
    assert not orphan.exists()


def test_cleanup_preserves_real_projects(workspace: Path) -> None:
    real = workspace / "us-invoice"
    real.mkdir()
    (real / "project.json").write_text(json.dumps({"slug": "us-invoice"}))
    cleanup_orphan_projects(workspace)
    assert real.exists()
    assert (real / "project.json").exists()


def test_cleanup_skips_sentinel_dirs(workspace: Path) -> None:
    """Anything with a leading `_` (e.g. `_staging`) or `.` belongs to a
    sibling subsystem (or the OS) — orphan cleanup must not touch it."""
    (workspace / "_staging").mkdir()
    (workspace / "_orphans").mkdir()
    (workspace / ".lock").mkdir()  # would shadow a flock file in real life
    cleanup_orphan_projects(workspace)
    assert (workspace / "_staging").exists()
    assert (workspace / "_orphans").exists()
    assert (workspace / ".lock").exists()


def test_cleanup_ignores_files_at_root(workspace: Path) -> None:
    (workspace / "stray.txt").write_text("hi")
    assert cleanup_orphan_projects(workspace) == 0
    assert (workspace / "stray.txt").exists()


def test_cleanup_missing_workspace_returns_zero(tmp_path: Path) -> None:
    """Safe to call before the workspace exists (CI smoke or fresh boot)."""
    ghost = tmp_path / "never-created"
    assert cleanup_orphan_projects(ghost) == 0


def test_cleanup_removes_multiple_orphans(workspace: Path) -> None:
    for name in ("untitled-1", "untitled-2", "untitled-3"):
        (workspace / name).mkdir()
    real = workspace / "real"
    real.mkdir()
    (real / "project.json").write_text("{}")
    assert cleanup_orphan_projects(workspace) == 3
    assert real.exists()


# ── tenancy: teams/ must survive (data-loss regression) ────────────────────


def test_cleanup_never_removes_teams_root(workspace: Path) -> None:
    """The `teams/` tenancy root carries no `project.json` of its own. Before
    the fix, a backend restart rmtree'd the entire teams/ tree — every team's
    every project. It must be hard-exempt even when it holds tenant projects."""
    proj = workspace / "teams" / "t_abc" / "us-invoice"
    proj.mkdir(parents=True)
    (proj / "project.json").write_text(json.dumps({"slug": "us-invoice"}))
    assert cleanup_orphan_projects(workspace) == 0
    assert proj.exists()
    assert (proj / "project.json").exists()


def test_cleanup_preserves_empty_team_workspace(workspace: Path) -> None:
    """A freshly-minted team dir with no projects (only `_chats`) is the durable
    tenant root, not an orphan — it must never be swept."""
    team = workspace / "teams" / "t_empty"
    (team / "_chats").mkdir(parents=True)
    assert cleanup_orphan_projects(workspace) == 0
    assert team.exists()


def test_cleanup_reaps_orphans_inside_team_workspace(workspace: Path) -> None:
    """Partial-write debris can land under teams/{tid}/ too. We still reap it
    one level deep — without touching the team dir or sibling real projects."""
    team = workspace / "teams" / "t_abc"
    real = team / "real"
    real.mkdir(parents=True)
    (real / "project.json").write_text("{}")
    orphan = team / "untitled-260514-152406"
    (orphan / "chats").mkdir(parents=True)  # half-written
    assert cleanup_orphan_projects(workspace) == 1
    assert not orphan.exists()
    assert real.exists()
    assert team.exists()


# ── create_project rollback ────────────────────────────────────────────────


async def test_create_project_rolls_back_on_atomic_write_failure(
    workspace: Path,
) -> None:
    """If the second atomic_write_json call raises (e.g. model_path), the
    half-written project dir must be removed entirely — otherwise it would
    haunt `workspace/` as un-listable debris."""
    real_atomic = __import__("app.workspace.atomic", fromlist=["atomic_write_json"]).atomic_write_json
    calls = {"n": 0}

    def flaky_write(path: Path, blob: object) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk full mid-write")
        real_atomic(path, blob)

    with patch("app.tools.projects.atomic_write_json", side_effect=flaky_write):
        with pytest.raises(OSError, match="simulated disk full"):
            await create_project(workspace, name="will-fail")

    # The slug it would have chosen is `will-fail` — must not exist on disk.
    assert not (workspace / "will-fail").exists()


async def test_create_project_happy_path_unchanged(workspace: Path) -> None:
    """Regression guard: the rollback try/except must not swallow a real
    successful run. The project should exist with project.json + prompt +
    model files written."""
    out = await create_project(workspace, name="us-invoice")
    slug = out["slug"]
    pdir = workspace / slug
    assert (pdir / "project.json").exists()
    assert (pdir / "prompts" / "pr_baseline.json").exists()
    assert (pdir / "models" / "m_default.json").exists()
    # cleanup pass must NOT remove this project (project.json present).
    cleanup_orphan_projects(workspace)
    assert pdir.exists()
