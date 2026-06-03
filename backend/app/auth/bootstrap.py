"""Superuser bootstrap — the act that flips emerge into tenant mode.

Creating the first superuser also (a) mints the bootstrap team, (b) migrates
all existing flat projects into it, and (c) makes the superuser a member with
that team active — so the operator logs in and immediately sees the migrated
work. Idempotent: if a superuser already exists, it's returned unchanged and no
re-migration happens.

Run via `python -m app.auth.create_superuser` (env-seeded or interactive).
"""

from __future__ import annotations

from pathlib import Path

from app.auth import store
from app.auth.models import User
from app.config import get_settings
from app.workspace.migrate_tenancy import migrate_to_tenancy


async def bootstrap_superuser(
    root: Path, *, email: str, password: str, full_name: str = "Superuser"
) -> User:
    for u in await store.list_users(root):
        if u.is_superuser:
            return u  # already bootstrapped — idempotent

    su = await store.create_user(
        root, email=email, password=password, full_name=full_name, is_superuser=True,
    )
    team = await store.create_team(
        root, name=get_settings().bootstrap_team_name, created_by=su.id,
    )
    migrate_to_tenancy(root, team.id)
    su, _team = await store.add_member(root, team.id, su.id)  # active = bootstrap team
    return su
