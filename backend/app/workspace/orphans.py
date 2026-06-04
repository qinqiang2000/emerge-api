"""Startup-time cleanup for orphan project directories.

A project directory becomes an orphan when `create_project` mkdirs the
folder but a later step (atomic_write_json, schema serialisation, OS-level
error) fails before `project.json` is written. The rollback in
`tools.projects.create_project` covers the happy-path crash, but legacy
debris (`p_unset/`, `untitled-260514-152406/` observed during dogfood) and
any external process partial-write would otherwise linger forever — they
don't show up in `/lab/projects` (the listing filters on `project.json`
presence) yet still bloat `workspace/` and tempt `mkdir` collisions.

This runs once on FastAPI startup, alongside `staging.cleanup_stale`.

**Tenancy trap (data-loss, fixed 2026-06-04):** in tenant mode projects live
under `teams/{tid}/{slug}/`, not at the flat root. The `teams/` dir is NOT a
project and carries no `project.json` — so the naïve "remove any non-`_` root
dir without project.json" swept the *entire* `teams/` tree (every team's every
project) on every backend restart. We now (a) hard-exempt the `teams/` sentinel
at the root and (b) recurse one level into each team workspace so genuine
partial-write orphans there are still reaped, while a team dir itself is never
removed. See INSIGHTS.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.workspace.paths import teams_root
from app.workspace.trash import trash


logger = logging.getLogger(__name__)


def _sweep_dir(parent: Path, *, skip: frozenset[str] = frozenset()) -> int:
    """Soft-delete immediate child dirs of `parent` that look like a project
    candidate (a plain directory) but lack `project.json`.

    A child is exempt — never touched — when its name:
      * starts with `_` (sentinel/internal dirs like `_staging`, `_orphans`,
        `_chats`, `_trash`, `_logs`)
      * starts with `.` (`.lock`, `.DS_Store`, …)
      * is listed in `skip` (e.g. the `teams/` tenancy root)

    Orphans are MOVED to `parent/_trash/`, not `rmtree`'d — orphan detection has
    been wrong before (it once classified the whole `teams/` tree as debris), so
    even "junk" stays recoverable for the retention window.
    """
    removed = 0
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith(("_", ".")) or child.name in skip:
            continue
        if (child / "project.json").exists():
            continue
        # Orphan: no project.json. Log enough context to diagnose but not
        # so much we leak filesystem clutter into stdout on every restart.
        logger.warning("cleanup_orphan_projects: trashing %s (no project.json)", child)
        trash(parent, child)
        removed += 1
    return removed


def cleanup_orphan_projects(workspace: Path) -> int:
    """Remove orphan project directories that lack `project.json`.

    Sweeps two layers, never deleting a team workspace itself:
      * the flat root (open-mode projects + the legacy pre-tenancy layout) —
        with the `teams/` tenancy root hard-exempted
      * one level inside each `teams/{tid}/` (tenant-mode projects)

    Returns the number of orphan dirs removed; safe to call when the workspace
    doesn't exist yet (returns 0).
    """
    if not workspace.exists():
        return 0
    teams = teams_root(workspace)
    removed = _sweep_dir(workspace, skip=frozenset({teams.name}))
    if teams.is_dir():
        for team_dir in teams.iterdir():
            # Never remove the team workspace itself, even when it holds no
            # projects yet — it's the durable tenant root, not an orphan.
            if team_dir.is_dir() and not team_dir.name.startswith(("_", ".")):
                removed += _sweep_dir(team_dir)
    return removed
