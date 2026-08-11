"""Retention for `{project}/_export/` — the agent's deliverables drawer.

`_export/` is where the agent writes things it built *for the user*: a zip of
docs, a CSV, a self-contained HTML report. `emerge_extractor.md` tells it to
build there and then hand the path to `offer_download`. Nothing ever removed
them, so the drawer only grew. Measured on prod the day this shipped: one
project holding a **166 MB** `docs_海信日本.zip` — a re-derivable copy of its own
`docs/` — beside a 765-byte `prompts.zip`. The drawer is not small change.

**This module deletes nothing.** It is a *policy* — "this deliverable has aged
out" — and it hands the file to `trash()`, which is the existing retention
mechanism. `cleanup_trash` stays the single place user data is physically
destroyed. That matters here more than usual: an `_export/` entry is not always
re-derivable. A zip of `docs/` is, but a report the agent composed once is a
one-off, and telling them apart from the outside is not possible. So an expired
deliverable gets a second retention window rather than a delete.

Total lifetime is therefore `EXPORT_RETENTION_HOURS` +
`TRASH_RETENTION_HOURS` — a week in the drawer, then a fortnight in the bin,
restorable the whole time via `restore_from_trash`.

**Why a week.** Download capabilities live 24 h (`download_url._TTL_SECONDS`),
so a link handed out for a deliverable has long expired by the time the file
ages out; and re-producing one is a single agent turn. The one rough edge: a
token minted against a six-day-old file can outlive the sweep, and the click
then lands on `download.py`'s "the file this link pointed at no longer exists"
404. That is the correct answer — the bytes are in `_trash/`, not gone — and
it is preferable to keeping every deliverable forever so that no link can ever
go stale.

Named `deliverables`, not `exports`, to stay out of the way of `app/exports/`
(the publish-bundle builder) — a different `export` entirely.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from app.workspace.paths import teams_root
from app.workspace.trash import trash


logger = logging.getLogger(__name__)

# One week in the drawer. Then `_trash/` holds it for TRASH_RETENTION_HOURS more.
EXPORT_RETENTION_HOURS = 24.0 * 7

EXPORT_DIR_NAME = "_export"


def _sweep_project(workspace: Path, project_dir: Path, cutoff: float) -> int:
    """Trash entries directly under `project_dir/_export/` older than `cutoff`.

    `workspace` is the EFFECTIVE workspace (team dir in tenant mode, flat root
    in open mode) so the trashed entry's manifest `origin` is
    `{project}/_export/{name}` and a restore replays into the right place.

    Per-entry, not per-directory: a project routinely holds a stale zip next to
    a report written this morning, and `_export/` itself must survive so the
    agent's next `offer_download` has somewhere to write.
    """
    export_dir = project_dir / EXPORT_DIR_NAME
    if not export_dir.is_dir():
        return 0
    swept = 0
    for child in export_dir.iterdir():
        if child.name.startswith("."):  # .DS_Store and friends — not deliverables
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        logger.info(
            "cleanup_stale_exports: trashing %s (older than %.0fh)",
            child, EXPORT_RETENTION_HOURS,
        )
        if trash(workspace, child) is not None:
            swept += 1
    return swept


def cleanup_stale_exports(
    workspace: Path, max_age_hours: float = EXPORT_RETENTION_HOURS
) -> int:
    """Age out `_export/` deliverables across every project in ONE workspace.

    Returns how many entries were moved to trash. Safe when the workspace (or
    any project's `_export/`) doesn't exist.
    """
    if not workspace.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    teams = teams_root(workspace)
    swept = 0
    for child in workspace.iterdir():
        # Same exemption shape as `orphans._sweep_dir`: `_`/`.` sentinels are
        # not projects, and `teams/` is the tenancy root, walked separately by
        # `sweep_all_exports`.
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        if child.name == teams.name:
            continue
        if not (child / "project.json").exists():
            continue
        swept += _sweep_project(workspace, child, cutoff)
    return swept


def sweep_all_exports(
    workspace_root: Path, max_age_hours: float = EXPORT_RETENTION_HOURS
) -> int:
    """Age out deliverables across the flat root AND every team workspace.

    Mirrors the two-layer walk in `trash.purge_all_trash` /
    `orphans.cleanup_orphan_projects` — open mode keeps projects at the root,
    tenant mode keeps them one level inside `teams/{slug}/`. Called on startup.
    """
    total = cleanup_stale_exports(workspace_root, max_age_hours)
    teams = teams_root(workspace_root)
    if teams.is_dir():
        for team_dir in teams.iterdir():
            if team_dir.is_dir() and not team_dir.name.startswith(("_", ".")):
                total += cleanup_stale_exports(team_dir, max_age_hours)
    return total
