"""One-time, idempotent migration: backfill `Team.slug` + rename id-named dirs.

Pre-2026-06-04 team workspaces were `teams/{team_id}/` (opaque, agent-hostile).
They're now `teams/{slug}/` (human-readable). This migration, run on startup
before any request binds a team workspace:

  1. backfills `slug` on every team row that lacks one — `derive_slug(name)`,
     uniqued across the set + existing dir names, and
  2. renames the legacy on-disk `teams/{id}/` → `teams/{slug}/` when the
     id-named dir exists and the slug dir is free.

Re-running is a no-op once every row has a slug and no id-named dir remains.
Operates directly on `_auth/teams.json` (not via `auth.store`) to stay
dependency-light and avoid an import cycle.
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import team_workspace_dir, teams_path, teams_root
from app.workspace.slug import derive_slug, ensure_unique_slug


_log = logging.getLogger(__name__)


def migrate_team_dirs(root: Path) -> int:
    """Returns the number of team rows that gained a slug (0 on a no-op
    re-run). Dir renames are a side effect and don't affect the count."""
    path = teams_path(root)
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(rows, list) or not rows:
        return 0

    # Uniqueness universe: slugs already assigned + every existing dir name
    # under teams/ (so a fresh slug never lands on an occupied folder).
    taken: set[str] = {r["slug"] for r in rows if isinstance(r, dict) and r.get("slug")}
    troot = teams_root(root)
    if troot.is_dir():
        taken |= {c.name for c in troot.iterdir() if c.is_dir()}

    backfilled = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        tid = r.get("id")
        if not tid:
            continue
        slug = r.get("slug")
        if not slug:
            slug = ensure_unique_slug(
                derive_slug(r.get("name") or tid, fallback_prefix="team"), taken
            )
            r["slug"] = slug
            taken.add(slug)
            backfilled += 1
        # Rename the legacy id-named dir to the slug dir. Runs independently of
        # backfill so a prior crash between write + rename still heals.
        legacy = team_workspace_dir(root, tid)
        target = team_workspace_dir(root, slug)
        if tid != slug and legacy.is_dir() and not target.exists():
            shutil.move(str(legacy), str(target))
            _log.warning("migrate_team_dirs: renamed %s -> %s", legacy, target)

    if backfilled:
        atomic_write_json(path, rows)
    return backfilled
