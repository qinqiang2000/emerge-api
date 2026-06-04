"""Human-readable team directory handles (`teams/{slug}/`, not `teams/{id}/`).

Pins:
  1. create_team derives a slug from the name; collisions get suffixed; CJK is
     preserved (the whole point — `teams/荣耀/` reads, `teams/t_…/` doesn't).
  2. migrate_team_dirs backfills slug on legacy rows AND renames the id-named
     dir to the slug dir, idempotently.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.auth import store
from app.workspace.migrate_team_dirs import migrate_team_dirs
from app.workspace.paths import team_workspace_dir, teams_path


async def test_create_team_derives_slug(workspace: Path) -> None:
    t = await store.create_team(workspace, name="Honor", created_by="u_x")
    assert t.slug == "honor"


async def test_create_team_preserves_cjk(workspace: Path) -> None:
    t = await store.create_team(workspace, name="荣耀", created_by="u_x")
    assert t.slug == "荣耀"  # non-ASCII handle round-trips — agent-friendly


async def test_create_team_uniquifies_colliding_slugs(workspace: Path) -> None:
    a = await store.create_team(workspace, name="Acme", created_by="u_x")
    b = await store.create_team(workspace, name="ACME", created_by="u_x")
    assert a.slug == "acme"
    assert b.slug == "acme-2"  # same derived slug → suffixed


async def test_migrate_backfills_slug_and_renames_dir(workspace: Path) -> None:
    # Simulate a pre-slug install: a teams.json row with no slug + an id-named
    # workspace dir holding a project.
    tid = "t_legacy01"
    teams_path(workspace).parent.mkdir(parents=True, exist_ok=True)
    teams_path(workspace).write_text(json.dumps([
        {"id": tid, "name": "Honor", "invite_token": "tok", "created_by": "u_x",
         "member_ids": [], "created_at": "2026-06-03T00:00:00Z"},
    ]))
    legacy = team_workspace_dir(workspace, tid)
    (legacy / "us-invoice").mkdir(parents=True)
    (legacy / "us-invoice" / "project.json").write_text("{}")

    n = migrate_team_dirs(workspace)

    assert n == 1
    team = await store.get_team(workspace, tid)
    assert team is not None and team.slug == "honor"
    # dir renamed, project carried over; legacy id-named dir gone
    assert (team_workspace_dir(workspace, "honor") / "us-invoice" / "project.json").exists()
    assert not legacy.exists()


async def test_migrate_team_dirs_is_idempotent(workspace: Path) -> None:
    await store.create_team(workspace, name="Honor", created_by="u_x")
    # First run: slug already set by create_team → nothing to backfill.
    assert migrate_team_dirs(workspace) == 0
    assert migrate_team_dirs(workspace) == 0
