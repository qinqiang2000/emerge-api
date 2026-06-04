"""One-time, idempotent migration: flat pre-tenancy projects → bootstrap team.

Before 2026-06-03 projects lived at `workspace_root/{slug}/`. Multi-tenancy
nests them under `workspace_root/teams/{team_id}/{slug}/`. This migration runs
exactly once — as part of `create_superuser` (the act that flips the platform
into tenant mode), NOT as an unconditional startup hook (which would nest
projects before any team exists).

It moves only directories that carry a `project.json`; workspace-global
artifacts (`_auth/`, `_keys.json`, `_published/`, `.cache/`, `_job_locks/`,
`teams/` itself, dotfiles) stay at the root. Re-running is a no-op once the
root has no project dirs left.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.workspace.paths import team_workspace_dir


def migrate_to_tenancy(root: Path, team_dirname: str) -> list[str]:
    """Move every flat project dir at `root` into `teams/{team_dirname}/`.
    `team_dirname` is the bootstrap team's slug (the human-readable folder name).
    Returns the slugs moved (empty on a no-op re-run)."""
    dest = team_workspace_dir(root, team_dirname)
    dest.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "project.json").exists():
            shutil.move(str(child), str(dest / child.name))
            moved.append(child.name)
    return moved
