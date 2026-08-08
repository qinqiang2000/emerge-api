"""Soft-delete (`_trash/`) contracts.

Pins the safety net that replaced raw `rmtree` on user-data delete paths:
  1. trash() MOVES (not destroys) and is recoverable; non-existent → no-op.
  2. name collisions within one second get a numeric suffix.
  3. cleanup_trash purges only past-retention entries (by mtime).
  4. purge_all_trash walks the flat root AND every team workspace.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from app.workspace.paths import trash_root
from app.workspace.trash import (
    TrashError,
    cleanup_trash,
    list_trash,
    purge_all_trash,
    restore_from_trash,
    trash,
)


def test_trash_moves_and_is_recoverable(workspace: Path) -> None:
    proj = workspace / "us-invoice"
    (proj / "docs").mkdir(parents=True)
    (proj / "project.json").write_text('{"slug": "us-invoice"}')

    dest = trash(workspace, proj)

    assert dest is not None
    assert not proj.exists()  # gone from the live tree
    assert dest.parent == trash_root(workspace)
    # Every entry is a manifest bundle — including single-member ones. The
    # manifest is what makes restore possible: without a recorded origin you
    # know an `ex_9f3` was deleted but not which project owned it.
    manifest = json.loads((dest / "_manifest.json").read_text())
    assert [m["origin"] for m in manifest["members"]] == ["us-invoice"]
    stored = dest / manifest["members"][0]["stored"]
    assert (stored / "project.json").read_text() == '{"slug": "us-invoice"}'

    # Recovery is the tool's job, not a hand-rolled `mv`.
    out = restore_from_trash(workspace, dest.name)
    assert out["kind"] == "project"
    assert (proj / "project.json").read_text() == '{"slug": "us-invoice"}'
    assert (proj / "docs").is_dir()
    assert not dest.exists()          # entry consumed
    assert list_trash(workspace) == []


def test_restore_refuses_when_origin_is_occupied(workspace: Path) -> None:
    # All-or-nothing: a half-restored doc (file back, reviewed JSON refused)
    # looks restored while its ground truth is still in the bin.
    proj = workspace / "us-invoice"
    proj.mkdir()
    (proj / "project.json").write_text("{}")
    dest = trash(workspace, proj)
    assert dest is not None

    proj.mkdir()  # something took the name back
    (proj / "project.json").write_text('{"new": true}')

    rows = list_trash(workspace)
    assert rows[0]["restorable"] is False
    assert rows[0]["blocked_reason"].startswith("origin_occupied:")

    with pytest.raises(TrashError, match="already exists"):
        restore_from_trash(workspace, dest.name)
    assert (proj / "project.json").read_text() == '{"new": true}'  # untouched
    assert dest.exists()                                           # still recoverable


def test_restore_needs_the_owning_project_to_exist(workspace: Path) -> None:
    # A doc restored into a vanished project would leave a dir with no
    # project.json — which the orphan sweeper would trash straight back.
    proj = workspace / "us-invoice"
    (proj / "docs").mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    doc = proj / "docs" / "a.pdf"
    doc.write_bytes(b"%PDF-")

    dest = trash(workspace, doc)
    assert dest is not None
    shutil.rmtree(proj)

    with pytest.raises(TrashError, match="no longer exists"):
        restore_from_trash(workspace, dest.name)


def test_list_trash_flags_legacy_entries_but_still_shows_them(workspace: Path) -> None:
    # Entries trashed before the manifest existed record no origin. "It's here
    # but I can't put it back automatically" beats hiding the row.
    legacy = trash_root(workspace) / "20260101T000000Z-old-thing"
    legacy.mkdir(parents=True)
    (legacy / "project.json").write_text("{}")

    rows = list_trash(workspace)
    assert len(rows) == 1
    assert rows[0]["entry"] == legacy.name
    assert rows[0]["restorable"] is False
    assert rows[0]["blocked_reason"] == "legacy_no_manifest"

    with pytest.raises(TrashError, match="predates"):
        restore_from_trash(workspace, legacy.name)


def test_list_trash_names_things_semantically(workspace: Path) -> None:
    # A row reading `ex_0ojxll…` is unusable for deciding what to restore.
    proj = workspace / "us-invoice"
    edir = proj / "experiments" / "ex_abc"
    edir.mkdir(parents=True)
    (proj / "project.json").write_text("{}")
    (edir / "meta.json").write_text(json.dumps({"experiment_id": "ex_abc", "label": "Baseline v2 × flash"}))

    trash(workspace, edir)
    row = list_trash(workspace)[0]
    assert row["kind"] == "experiment"
    assert row["name"] == "Baseline v2 × flash"
    assert row["project"] == "us-invoice"


def test_restore_rejects_path_traversal(workspace: Path) -> None:
    (workspace / "outside").mkdir()
    for bad in ("../outside", "a/b", ".hidden"):
        with pytest.raises(TrashError):
            restore_from_trash(workspace, bad)


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


def test_trash_stamps_deletion_time_so_retention_starts_now(workspace: Path) -> None:
    """An OLD project must still get its full retention window after deletion.

    `shutil.move` on one filesystem is `rename(2)`, which preserves mtime, and
    `cleanup_trash` ages by mtime — so without an explicit re-stamp anything
    older than the window is purge-eligible the instant it's trashed, and the
    next startup purge destroys it with no recovery window at all.
    """
    proj = _mk(workspace, "ancient")
    ancient = time.time() - 30 * 24 * 3600  # last touched a month ago
    os.utime(proj, (ancient, ancient))

    dest = trash(workspace, proj)
    assert dest is not None

    # Retention is measured from the delete, not from the last edit.
    assert dest.stat().st_mtime > time.time() - 60
    assert cleanup_trash(workspace, max_age_hours=24.0 * 14) == 0
    assert dest.exists()


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
