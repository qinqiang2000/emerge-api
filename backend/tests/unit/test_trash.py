"""Soft-delete (`_trash/`) contracts.

Pins the safety net that replaced raw `rmtree` on user-data delete paths:
  1. trash() MOVES (not destroys) and is recoverable; non-existent → no-op.
  2. name collisions within one second get a numeric suffix.
  3. cleanup_trash purges only past-retention entries (by mtime).
  4. purge_all_trash walks the flat root AND every team workspace.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from app.workspace.paths import trash_root
from app.workspace.trash import cleanup_trash, purge_all_trash, trash


def test_trash_moves_and_is_recoverable(workspace: Path) -> None:
    proj = workspace / "us-invoice"
    (proj / "docs").mkdir(parents=True)
    (proj / "project.json").write_text('{"slug": "us-invoice"}')

    dest = trash(workspace, proj)

    assert dest is not None
    assert not proj.exists()  # gone from the live tree
    assert dest.parent == trash_root(workspace)
    # The trashed copy keeps its contents — recovery is a plain `mv` back.
    assert (dest / "project.json").read_text() == '{"slug": "us-invoice"}'
    assert (dest / "docs").is_dir()


def test_trash_missing_path_is_noop(workspace: Path) -> None:
    assert trash(workspace, workspace / "ghost") is None
    assert not trash_root(workspace).exists()  # no empty bin created


def test_trash_name_collision_gets_suffix(workspace: Path) -> None:
    first = workspace / "dup"
    first.mkdir()
    d1 = trash(workspace, first)
    # Recreate same name, trash again in (likely) the same second.
    second = workspace / "dup"
    second.mkdir()
    d2 = trash(workspace, second)
    assert d1 != d2
    assert d1 is not None and d2 is not None
    assert d1.exists() and d2.exists()


def test_cleanup_trash_purges_only_expired(workspace: Path) -> None:
    old = trash(workspace, _mk(workspace, "old"))
    fresh = trash(workspace, _mk(workspace, "fresh"))
    assert old is not None and fresh is not None
    # Backdate `old` past the retention window.
    past = time.time() - 100 * 3600
    os.utime(old, (past, past))

    removed = cleanup_trash(workspace, max_age_hours=72.0)

    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_cleanup_trash_missing_bin_returns_zero(workspace: Path) -> None:
    assert cleanup_trash(workspace) == 0


def test_purge_all_trash_walks_root_and_teams(workspace: Path) -> None:
    # Root-level trash (open mode) + a team workspace's trash (tenant mode).
    root_old = trash(workspace, _mk(workspace, "root-proj"))
    team = workspace / "teams" / "t_abc"
    team.mkdir(parents=True)
    team_old = trash(team, _mk(team, "team-proj"))
    assert root_old is not None and team_old is not None
    past = time.time() - 100 * 3600
    for d in (root_old, team_old):
        os.utime(d, (past, past))

    removed = purge_all_trash(workspace, max_age_hours=72.0)

    assert removed == 2
    assert not root_old.exists()
    assert not team_old.exists()


def _mk(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    (d / "marker").write_text("x")
    return d
