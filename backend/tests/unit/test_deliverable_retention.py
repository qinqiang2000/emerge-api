"""`_export/` retention — deliverables age into `_trash/`, never into nothing.

Pins the contracts that make this safe to run unattended on every boot:
  1. Old deliverables move out of `_export/`; fresh ones stay.
  2. They move to TRASH — recoverable, with a manifest that restores them.
  3. `_export/` itself survives, and so does everything outside it.
  4. Both tenancy layers are swept (flat root + `teams/{slug}/`), and a team
     dir is never mistaken for a project.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from app.workspace.deliverables import (
    EXPORT_RETENTION_HOURS,
    cleanup_stale_exports,
    sweep_all_exports,
)
from app.workspace.trash import list_trash, restore_from_trash, trash, trash_root


def _project(workspace: Path, slug: str) -> Path:
    p = workspace / slug
    (p / "_export").mkdir(parents=True, exist_ok=True)
    (p / "project.json").write_text(json.dumps({"slug": slug}), encoding="utf-8")
    return p


def _aged(path: Path, hours: float, body: str = "payload") -> Path:
    """Write `path` and backdate its mtime by `hours`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    old = time.time() - hours * 3600
    os.utime(path, (old, old))
    return path


def test_stale_deliverable_is_swept_and_fresh_one_is_kept(workspace: Path) -> None:
    proj = _project(workspace, "us-invoice")
    stale = _aged(proj / "_export" / "docs.zip", EXPORT_RETENTION_HOURS + 1)
    fresh = _aged(proj / "_export" / "report.html", 1)

    assert cleanup_stale_exports(workspace) == 1
    assert not stale.exists()
    assert fresh.exists()
    # The drawer itself must survive — the agent's next `offer_download` needs
    # somewhere to write, and an absent dir would be a silent behaviour change.
    assert (proj / "_export").is_dir()


def test_swept_deliverable_is_recoverable(workspace: Path) -> None:
    """The red line: this path must never physically destroy user data.

    An `_export/` entry is not reliably re-derivable — a zip of `docs/` is, a
    report the agent composed once is not — so an expired deliverable gets a
    second retention window in `_trash/`, not a delete.
    """
    proj = _project(workspace, "us-invoice")
    _aged(proj / "_export" / "docs.zip", EXPORT_RETENTION_HOURS + 1, body="ZIPBYTES")
    cleanup_stale_exports(workspace)

    rows = list_trash(workspace)
    assert len(rows) == 1
    assert rows[0]["kind"] == "deliverable"
    assert rows[0]["name"] == "docs.zip"
    assert rows[0]["restorable"] is True

    restore_from_trash(workspace, rows[0]["entry"])
    restored = proj / "_export" / "docs.zip"
    assert restored.read_text(encoding="utf-8") == "ZIPBYTES"


def test_restore_restarts_the_retention_clock(workspace: Path) -> None:
    """Restoring a deliverable must survive the next boot.

    `shutil.move` preserves mtime, so a restored deliverable would come back
    still expired and get swept again on the next startup — the user's restore
    silently undone. Found by dogfooding 2026-08-11.
    """
    proj = _project(workspace, "us-invoice")
    _aged(proj / "_export" / "docs.zip", EXPORT_RETENTION_HOURS + 1)
    cleanup_stale_exports(workspace)
    restore_from_trash(workspace, list_trash(workspace)[0]["entry"])

    assert (proj / "_export" / "docs.zip").exists()
    # The next boot's sweep must leave it alone.
    assert cleanup_stale_exports(workspace) == 0
    assert (proj / "_export" / "docs.zip").exists()


def test_restore_preserves_mtime_for_everything_else(workspace: Path) -> None:
    """The clock reset is scoped to deliverables. A doc's timestamp is real
    metadata, and nothing outside `_export/` ages on mtime anyway."""
    proj = _project(workspace, "us-invoice")
    doc = _aged(proj / "docs" / "invoice.pdf", 5000)
    before = doc.stat().st_mtime
    trash(workspace, doc)
    restore_from_trash(workspace, list_trash(workspace)[0]["entry"])

    assert doc.stat().st_mtime == before


def test_sweep_ignores_everything_outside_export(workspace: Path) -> None:
    """Age is only a reason to sweep INSIDE `_export/`.

    An old `docs/` sample or an old `reviewed/` ground truth is not stale — it
    is the project. Nothing else in the tree may be swept on age.
    """
    proj = _project(workspace, "us-invoice")
    old_doc = _aged(proj / "docs" / "invoice.pdf", EXPORT_RETENTION_HOURS * 10)
    old_gt = _aged(proj / "reviewed" / "invoice.pdf.json", EXPORT_RETENTION_HOURS * 10)
    old_schema = _aged(proj / "schema.json", EXPORT_RETENTION_HOURS * 10, body="[]")

    assert cleanup_stale_exports(workspace) == 0
    assert old_doc.exists() and old_gt.exists() and old_schema.exists()


def test_sweep_skips_non_projects_and_sentinels(workspace: Path) -> None:
    """A dir without `project.json` is not a project, so its `_export/` (if it
    somehow has one) is not ours to age. Sentinels are exempt outright —
    trashing out of `_trash/` or `_staging/` would be a loop."""
    stray = workspace / "not-a-project"
    _aged(stray / "_export" / "x.zip", EXPORT_RETENTION_HOURS + 1)
    sentinel = workspace / "_chats"
    _aged(sentinel / "_export" / "y.zip", EXPORT_RETENTION_HOURS + 1)

    assert cleanup_stale_exports(workspace) == 0
    assert (stray / "_export" / "x.zip").exists()
    assert (sentinel / "_export" / "y.zip").exists()


def test_sweep_walks_both_tenancy_layers(workspace: Path) -> None:
    """Open mode keeps projects at the root, tenant mode one level inside
    `teams/{slug}/`. `sweep_all_exports` must reach both — and must not treat
    `teams/` itself as a project (the 2026-06-04 shape of accident)."""
    root_proj = _project(workspace, "open-mode-proj")
    _aged(root_proj / "_export" / "a.zip", EXPORT_RETENTION_HOURS + 1)

    team_ws = workspace / "teams" / "发票云空间"
    team_proj = _project(team_ws, "振兴_20260707")
    _aged(team_proj / "_export" / "b.zip", EXPORT_RETENTION_HOURS + 1)

    assert sweep_all_exports(workspace) == 2
    assert not (root_proj / "_export" / "a.zip").exists()
    assert not (team_proj / "_export" / "b.zip").exists()
    assert team_ws.is_dir()

    # Each half landed in ITS OWN workspace's trash — a team's deleted data
    # must never cross the tenant boundary into the root bin.
    assert [r["name"] for r in list_trash(workspace)] == ["a.zip"]
    assert [r["name"] for r in list_trash(team_ws)] == ["b.zip"]


def test_sweep_handles_directories_inside_export(workspace: Path) -> None:
    """The agent can `mkdir` inside `_export/`; a stale subtree ages out whole."""
    proj = _project(workspace, "us-invoice")
    subdir = proj / "_export" / "batch-01"
    _aged(subdir / "part.csv", EXPORT_RETENTION_HOURS + 1)
    old = time.time() - (EXPORT_RETENTION_HOURS + 1) * 3600
    os.utime(subdir, (old, old))

    assert cleanup_stale_exports(workspace) == 1
    assert not subdir.exists()
    assert (proj / "_export").is_dir()


def test_sweep_is_a_noop_on_a_clean_workspace(workspace: Path) -> None:
    """No projects, no `_export/`, no trash root created as a side effect."""
    assert cleanup_stale_exports(workspace) == 0
    assert sweep_all_exports(workspace) == 0
    assert not trash_root(workspace).exists()
