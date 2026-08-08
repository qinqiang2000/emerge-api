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

import json
import logging
import os
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
    # Stamp the trash entry with "deleted at NOW". `shutil.move` within one
    # filesystem is `rename(2)`, which PRESERVES the original mtime — and
    # `cleanup_trash` ages entries by mtime. Without this, deleting anything
    # older than the retention window lands it in trash already expired, so the
    # next startup purge destroys it with zero recovery window — the exact
    # opposite of what trash is for. (Observed 2026-08-07: two experiments last
    # written 23 days earlier were purge-eligible the moment they were deleted.)
    os.utime(dest, None)
    logger.info("trash: %s -> %s", path, dest)
    return dest


def trash_bundle(
    workspace: Path,
    label: str,
    members: list[tuple[str, Path]],
) -> Path | None:
    """Move several related paths into ONE `_trash/{ts}-{label}/` entry, with a
    `_manifest.json` recording where each piece came from. Returns the bundle
    dir, or None when no member exists on disk.

    `members` is `[(role, path), ...]`. `role` names what the file was
    (``doc``, ``reviewed``, ``experiment/ex_123``) — purely descriptive; the
    manifest's `origin` (workspace-relative source path) is what a restore
    actually replays.

    Why a bundle rather than N calls to `trash()`: deleting one doc touches the
    file plus every artifact keyed off its name — sidecar meta, draft
    prediction, the reviewed ground truth, one prediction per experiment. Those
    are scattered across the project tree, so trashing them one by one produces
    half a dozen unrelated-looking trash entries and no way to tell they were a
    single delete. One bundle keeps the delete recoverable as a unit.
    """
    present = [(role, p) for role, p in members if p.exists()]
    if not present:
        return None

    root = trash_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / f"{ts}-{label}"
    n = 1
    while dest.exists():  # same label trashed within one second
        n += 1
        dest = root / f"{ts}-{label}-{n}"
    dest.mkdir(parents=True)

    entries: list[dict[str, str]] = []
    for i, (role, path) in enumerate(present):
        # Flat storage names: members can share a basename (`x.pdf.json` lives
        # under .meta/, predictions/_draft/ and every experiment dir), so the
        # index prefix is what keeps them from colliding inside the bundle.
        stored = f"{i:02d}__{path.name}"
        shutil.move(str(path), str(dest / stored))
        try:
            origin = str(path.relative_to(workspace))
        except ValueError:  # pragma: no cover — member outside the workspace
            origin = str(path)
        entries.append({"role": role, "origin": origin, "stored": stored})

    (dest / "_manifest.json").write_text(
        json.dumps(
            {
                "label": label,
                "trashed_at": datetime.now(timezone.utc).isoformat(),
                "members": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.utime(dest, None)  # same mtime-stamp reasoning as `trash()` above
    logger.info("trash_bundle: %s (%d members) -> %s", label, len(entries), dest)
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
