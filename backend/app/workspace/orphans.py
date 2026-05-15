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
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path


logger = logging.getLogger(__name__)


def cleanup_orphan_projects(workspace: Path) -> int:
    """Remove top-level project directories that lack `project.json`.

    A dir qualifies as a project candidate when:
      * it's an immediate child of `workspace/`
      * the name does NOT start with `_` (sentinel/internal dirs like
        `_staging`, `_orphans`, `_logs` are off-limits)
      * the name does NOT start with `.` (`.lock`, `.DS_Store`, etc.)

    If a candidate is missing `project.json`, it's removed via
    `shutil.rmtree`. The `_staging` directory is owned by
    `staging.cleanup_stale` and is left alone here. Returns the number of
    orphan dirs removed; safe to call when the workspace doesn't exist
    yet (returns 0).
    """
    if not workspace.exists():
        return 0
    removed = 0
    for child in workspace.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith(("_", ".")):
            continue
        if (child / "project.json").exists():
            continue
        # Orphan: no project.json. Log enough context to diagnose but not
        # so much we leak filesystem clutter into stdout on every restart.
        logger.warning("cleanup_orphan_projects: removing %s (no project.json)", child)
        shutil.rmtree(child, ignore_errors=True)
        removed += 1
    return removed
