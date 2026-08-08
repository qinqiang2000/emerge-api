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
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

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

    This is `trash_bundle` with a single member: the entry is a directory
    holding the moved payload plus a `_manifest.json` recording where it came
    from. The manifest is what makes restore possible at all — a bare
    `_trash/{ts}-{name}` tells you an experiment called `ex_9f3` was deleted
    but NOT which project owned it, so there is nowhere to put it back.
    """
    return trash_bundle(workspace, path.name, [("item", path)])


def _new_entry_dir(workspace: Path, label: str) -> Path:
    root = trash_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / f"{ts}-{label}"
    n = 1
    while dest.exists():  # same label trashed within one second
        n += 1
        dest = root / f"{ts}-{label}-{n}"
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

    dest = _new_entry_dir(workspace, label)
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


class TrashError(Exception):
    """Restore refused — entry unknown, unreadable, or its origin is occupied."""


def _read_manifest(entry: Path) -> dict[str, Any] | None:
    mp = entry / "_manifest.json"
    if not mp.is_file():
        return None
    try:
        blob = json.loads(mp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return blob if isinstance(blob, dict) and isinstance(blob.get("members"), list) else None


def _classify(origins: list[str]) -> str:
    """What kind of thing was deleted, inferred from where it used to live.

    Deliberately derived from `origin` rather than stored at delete time: the
    delete paths that predate the manifest (and any future caller that just
    calls `trash()`) get classified for free, and there is no second field to
    keep in sync with the first.
    """
    first = origins[0] if origins else ""
    parts = PurePosixPath(first).parts
    if len(parts) == 1:
        return "project"
    if "docs" in parts:
        return "doc"
    if "prompts" in parts:
        return "prompt"
    if "models" in parts:
        return "model"
    if "experiments" in parts:
        return "experiment"
    return "item"


def _display_name(entry: Path, kind: str, origins: list[str], members: list[dict]) -> str:
    """Human-facing name for a trash row. Prefers the object's own `label` over
    its id: a row reading `ex_0ojxll…` is unusable for deciding what to restore
    (see the "address things by semantic name" rule). Falls back to the
    filename when there's no label to read."""
    first = PurePosixPath(origins[0]) if origins else PurePosixPath("")
    stored = entry / members[0]["stored"] if members else None

    def _label_from(p: Path | None) -> str | None:
        if p is None or not p.exists():
            return None
        target = p / "meta.json" if p.is_dir() else p
        if not target.is_file() or target.suffix != ".json":
            return None
        try:
            blob = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        label = blob.get("label") or blob.get("name")
        return str(label) if label else None

    if kind in ("experiment", "model", "prompt"):
        label = _label_from(stored)
        if label:
            return label
    return first.name or entry.name


def list_trash(workspace: Path) -> list[dict[str, Any]]:
    """Everything recoverable in this workspace's trash, newest first.

    Each row: `{entry, name, kind, project, deleted_at, expires_at,
    member_count, restorable, blocked_reason}`. `entry` is the directory name
    and the handle `restore_from_trash` takes.

    `restorable` is false for entries trashed before the manifest existed
    (they record no origin, so there is no way to know where an `ex_xxx` came
    from) and for entries whose origin is occupied again. Those still get
    listed — "it's here but I can't put it back automatically, go look at this
    path" beats pretending the delete never happened.
    """
    root = trash_root(workspace)
    if not root.is_dir():
        return []

    rows: list[dict[str, Any]] = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue

        manifest = _read_manifest(entry)
        members = manifest["members"] if manifest else []
        origins = [str(m.get("origin", "")) for m in members]
        kind = _classify(origins) if origins else "item"

        blocked: str | None = None
        if manifest is None:
            blocked = "legacy_no_manifest"
        else:
            occupied = [o for o in origins if (workspace / o).exists()]
            if occupied:
                blocked = f"origin_occupied:{occupied[0]}"

        deleted_at = datetime.fromtimestamp(mtime, timezone.utc)
        project = ""
        if origins:
            parts = PurePosixPath(origins[0]).parts
            project = parts[0] if len(parts) > 1 else ""

        rows.append({
            "entry": entry.name,
            "name": _display_name(entry, kind, origins, members) if members else entry.name,
            "kind": kind,
            "project": project,
            "deleted_at": deleted_at.isoformat(),
            "expires_at": (
                deleted_at + timedelta(hours=TRASH_RETENTION_HOURS)
            ).isoformat(),
            "member_count": len(members),
            "restorable": blocked is None,
            "blocked_reason": blocked,
        })

    rows.sort(key=lambda r: r["deleted_at"], reverse=True)
    return rows


def restore_from_trash(workspace: Path, entry_name: str) -> dict[str, Any]:
    """Put one trash entry back where it came from, replaying its manifest.

    All-or-nothing on conflicts: if ANY member's origin is occupied, nothing
    moves and `TrashError` names the collision. A half-restored doc (file back,
    reviewed JSON refused) is worse than a clean refusal — it looks restored
    while its ground truth is still in the bin.

    Parent dirs are recreated as needed, so a doc can come back into a project
    whose `docs/` was emptied. It canNOT come back into a project that no
    longer exists — that would leave a directory with no `project.json`, which
    the orphan sweeper would then trash right back.

    Returns `{entry, restored: [origins], kind}`."""
    root = trash_root(workspace)
    entry = root / entry_name
    # Containment: `entry_name` arrives from HTTP. Resolve and require the
    # result to still sit directly under this workspace's trash root.
    if "/" in entry_name or "\\" in entry_name or entry_name.startswith("."):
        raise TrashError(f"invalid trash entry: {entry_name}")
    if not entry.is_dir():
        raise TrashError(f"no such trash entry: {entry_name}")

    manifest = _read_manifest(entry)
    if manifest is None:
        raise TrashError(
            f"{entry_name} predates the delete manifest, so its original "
            "location was never recorded — restore it by hand from _trash/"
        )
    members = manifest["members"]

    targets: list[tuple[Path, Path]] = []
    for m in members:
        origin = workspace / str(m["origin"])
        stored = entry / str(m["stored"])
        if origin.exists():
            raise TrashError(f"already exists, refusing to overwrite: {m['origin']}")
        if not stored.exists():
            raise TrashError(f"missing from the trash entry: {m['stored']}")
        targets.append((stored, origin))

    kind = _classify([str(m.get("origin", "")) for m in members])
    if kind != "project":
        # Everything below project level needs its owner to still be there.
        first = PurePosixPath(str(members[0]["origin"]))
        if len(first.parts) > 1:
            owner = workspace / first.parts[0]
            if not (owner / "project.json").exists():
                raise TrashError(
                    f"project '{first.parts[0]}' no longer exists — restore it first"
                )

    for stored, origin in targets:
        origin.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(stored), str(origin))

    shutil.rmtree(entry, ignore_errors=True)
    logger.info("restore_from_trash: %s -> %d member(s)", entry_name, len(targets))
    return {
        "entry": entry_name,
        "kind": kind,
        "restored": [str(m["origin"]) for m in members],
    }


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
