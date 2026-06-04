"""Soft-delete: MOVE user data to `_trash/` instead of `rmtree`-ing it.

emerge has no DB — a project IS its folder. A physical `rmtree` of user data is
therefore irreversible loss (the 2026-06-04 incident: orphan cleanup rmtree'd
the entire `teams/` tree on a backend restart; workspace is gitignored, so no
recovery). `trash()` is the safety net beneath every delete path: it renames the
target under `workspace/_trash/{ts}-{name}/`, so the delete is reversible until
retention purges it.

Two ideas kept separate on purpose:
  * **Durability** is already guaranteed by `atomic_write_json` + flock — a file
    on disk is always self-consistent. Trash does NOT add durability.
  * **Reversibility** is what trash adds. A move is atomic within one workspace
    (same filesystem → `rename(2)`), so for `delete_project` it doubles as the
    tombstone (the live `project.json` path vanishes in one step) AND keeps the
    `project.json` in the trashed copy for recovery.

Retention is generous (`TRASH_RETENTION_HOURS`, 14d) — this is deleted human
work, not transient upload staging (`_staging/`, 24h). Purged on startup by
`cleanup_trash`, mirrored across the root + every team workspace.
"""
from __future__ import annotations

import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from app.workspace.paths import teams_root, trash_root


logger = logging.getLogger(__name__)

# Deleted user data lingers two weeks before hard purge. Long enough that a
# "wait, I needed that" surfaces; short enough that trash doesn't grow forever.
TRASH_RETENTION_HOURS = 24.0 * 14


def trash(workspace: Path, path: Path) -> Path | None:
    """Move `path` into `workspace/_trash/{ts}-{name}/`. Returns the trash
    destination, or None when `path` doesn't exist (idempotent no-op).

    `workspace` is the EFFECTIVE workspace the path belongs to (a team dir in
    tenant mode, the flat root in open mode) — trash lands inside it, never
    crossing the tenant boundary. The move is atomic on a single filesystem.
    """
    if not path.exists():
        return None
    root = trash_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / f"{ts}-{path.name}"
    n = 1
    while dest.exists():  # same name trashed within one second
        n += 1
        dest = root / f"{ts}-{path.name}-{n}"
    shutil.move(str(path), str(dest))
    logger.info("trash: %s -> %s", path, dest)
    return dest


def cleanup_trash(workspace: Path, max_age_hours: float = TRASH_RETENTION_HOURS) -> int:
    """Hard-purge trash entries older than `max_age_hours`. Returns the count
    removed. Safe when the trash root is missing (returns 0). This is the ONLY
    place user data is physically destroyed — and only after the retention
    window, by mtime (set when the entry was trashed)."""
    root = trash_root(workspace)
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for child in root.iterdir():
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed


def purge_all_trash(
    workspace_root: Path, max_age_hours: float = TRASH_RETENTION_HOURS
) -> int:
    """Purge expired trash across the flat root AND every team workspace — the
    two layers where `_trash/` can appear (open mode vs tenant mode). Mirrors
    the two-layer walk in `orphans.cleanup_orphan_projects`. Called on startup.
    """
    total = cleanup_trash(workspace_root, max_age_hours)
    teams = teams_root(workspace_root)
    if teams.is_dir():
        for team_dir in teams.iterdir():
            if team_dir.is_dir() and not team_dir.name.startswith(("_", ".")):
                total += cleanup_trash(team_dir, max_age_hours)
    return total
