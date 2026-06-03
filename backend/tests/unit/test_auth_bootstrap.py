"""T5/T6 — superuser bootstrap + flat→tenant project migration."""

from __future__ import annotations

import json
from pathlib import Path

from app.auth import store
from app.auth.bootstrap import bootstrap_superuser
from app.workspace.migrate_tenancy import migrate_to_tenancy
from app.workspace.paths import team_workspace_dir


def _make_project(root: Path, slug: str) -> None:
    d = root / slug
    d.mkdir(parents=True)
    (d / "project.json").write_text(json.dumps({"project_id": f"p_{slug}", "slug": slug}))


# --- migration --------------------------------------------------------------

def test_migrate_moves_only_project_dirs(workspace: Path) -> None:
    _make_project(workspace, "alpha")
    _make_project(workspace, "beta")
    (workspace / "_published").mkdir()  # global artifact — must stay put
    (workspace / "_keys.json").write_text("[]")

    moved = migrate_to_tenancy(workspace, "t_boot")
    assert set(moved) == {"alpha", "beta"}
    assert (team_workspace_dir(workspace, "t_boot") / "alpha" / "project.json").exists()
    assert (team_workspace_dir(workspace, "t_boot") / "beta" / "project.json").exists()
    assert not (workspace / "alpha").exists()
    # global artifacts untouched
    assert (workspace / "_published").exists()
    assert (workspace / "_keys.json").exists()


def test_migrate_is_idempotent(workspace: Path) -> None:
    _make_project(workspace, "alpha")
    assert migrate_to_tenancy(workspace, "t_boot") == ["alpha"]
    assert migrate_to_tenancy(workspace, "t_boot") == []  # no-op second run


# --- bootstrap --------------------------------------------------------------

async def test_bootstrap_creates_superuser_team_and_migrates(workspace: Path) -> None:
    _make_project(workspace, "legacy-proj")
    su = await bootstrap_superuser(workspace, email="root@x.com", password="pw")

    assert su.is_superuser is True
    assert su.active_team_id is not None
    # bootstrap team exists, superuser is a member
    team = await store.get_team(workspace, su.active_team_id)
    assert team is not None and su.id in team.member_ids
    # legacy project migrated under the bootstrap team
    assert (team_workspace_dir(workspace, team.id) / "legacy-proj" / "project.json").exists()
    assert not (workspace / "legacy-proj").exists()


async def test_bootstrap_is_idempotent(workspace: Path) -> None:
    su1 = await bootstrap_superuser(workspace, email="root@x.com", password="pw")
    su2 = await bootstrap_superuser(workspace, email="other@x.com", password="pw2")
    assert su1.id == su2.id  # returns the existing superuser
    # only one team created (no double-migrate / double-team)
    assert len(await store.list_teams(workspace)) == 1
    assert len(await store.list_users(workspace)) == 1


async def test_auth_configured_flips_after_bootstrap(workspace: Path) -> None:
    assert await store.auth_configured(workspace) is False  # open mode
    await bootstrap_superuser(workspace, email="root@x.com", password="pw")
    assert await store.auth_configured(workspace) is True  # tenant mode
