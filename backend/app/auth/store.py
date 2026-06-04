"""Filesystem-backed user/team store (no DB — emerge's spine).

`_auth/users.json` and `_auth/teams.json` are JSON arrays of rows at the TRUE
workspace root (cross-team global). Mutations take a single exclusive flock on
`_auth/.lock` so two concurrent signups can't lose-update each other or mint a
duplicate email; reads are lock-free (last-writer-wins is fine for the tiny N —
a handful of customer teams). Callers MUST pass `settings.workspace_root` (the
true root), never a per-team workspace.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from app.auth.lock import auth_lock
from app.auth.models import Team, User
from app.auth.passwords import hash_password
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_team_id, new_user_id
from app.workspace.paths import teams_path, users_path
from app.workspace.slug import derive_slug, ensure_unique_slug


class DuplicateEmailError(Exception):
    """Raised when create_user hits an email that already exists."""


class UserNotFoundError(Exception):
    pass


class TeamNotFoundError(Exception):
    pass


_UNSET = object()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _new_invite_token() -> str:
    return secrets.token_urlsafe(24)


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return blob if isinstance(blob, list) else []


async def auth_configured(root: Path) -> bool:
    """True once at least one user exists. This is the **single-tenant ↔
    multi-tenant switch**: while it returns False the whole platform runs in
    open mode (no auth, flat `workspace_root` — exactly the pre-2026-06-03
    behaviour, so the existing suite is untouched). It flips True the moment
    `create_superuser` mints the first user, at which point auth is enforced
    and projects resolve under `teams/{tid}/`."""
    return len(_read_rows(users_path(root))) > 0


# --- users ------------------------------------------------------------------

async def create_user(
    root: Path,
    *,
    email: str,
    password: str,
    full_name: str = "",
    display_name: str = "",
    is_superuser: bool = False,
) -> User:
    norm = _normalize_email(email)
    async with auth_lock(root):
        rows = _read_rows(users_path(root))
        if any(_normalize_email(r.get("email", "")) == norm for r in rows):
            raise DuplicateEmailError(norm)
        user = User(
            id=new_user_id(),
            email=norm,
            password_hash=hash_password(password),
            full_name=full_name,
            display_name=display_name or full_name,
            team_ids=[],
            active_team_id=None,
            is_superuser=is_superuser,
            created_at=_iso_now(),
        )
        rows.append(user.model_dump(mode="json"))
        atomic_write_json(users_path(root), rows)
    return user


async def get_user(root: Path, user_id: str) -> User | None:
    for r in _read_rows(users_path(root)):
        if r.get("id") == user_id:
            return User(**r)
    return None


async def get_user_by_email(root: Path, email: str) -> User | None:
    norm = _normalize_email(email)
    for r in _read_rows(users_path(root)):
        if _normalize_email(r.get("email", "")) == norm:
            return User(**r)
    return None


async def list_users(root: Path) -> list[User]:
    return [User(**r) for r in _read_rows(users_path(root))]


async def update_user(
    root: Path,
    user_id: str,
    *,
    full_name: str | None = None,
    display_name: str | None = None,
    new_password: str | None = None,
    active_team_id: object = _UNSET,
) -> User:
    async with auth_lock(root):
        rows = _read_rows(users_path(root))
        for i, r in enumerate(rows):
            if r.get("id") == user_id:
                if full_name is not None:
                    r["full_name"] = full_name
                if display_name is not None:
                    r["display_name"] = display_name
                if new_password is not None:
                    r["password_hash"] = hash_password(new_password)
                if active_team_id is not _UNSET:
                    r["active_team_id"] = active_team_id
                user = User(**r)
                rows[i] = user.model_dump(mode="json")
                atomic_write_json(users_path(root), rows)
                return user
    raise UserNotFoundError(user_id)


# --- teams ------------------------------------------------------------------

async def create_team(root: Path, *, name: str, created_by: str) -> Team:
    """Mint a team. `created_by` is audit-only (no owner privilege) and is NOT
    auto-added as a member — the superuser-creator is not a tenant user; the
    first customer joins via the invite link. Members arrive through signup /
    add_member.

    The team's workspace dir is `teams/{slug}/` (human-readable), so the slug is
    derived from the name and made unique across existing team slugs here, under
    the same lock that appends the row — two teams named "荣耀" can't race to the
    same folder."""
    async with auth_lock(root):
        rows = _read_rows(teams_path(root))
        taken = {r.get("slug") for r in rows if r.get("slug")}
        slug = ensure_unique_slug(derive_slug(name, fallback_prefix="team"), taken)
        team = Team(
            id=new_team_id(),
            name=name.strip(),
            slug=slug,
            invite_token=_new_invite_token(),
            created_by=created_by,
            member_ids=[],
            created_at=_iso_now(),
        )
        rows.append(team.model_dump(mode="json"))
        atomic_write_json(teams_path(root), rows)
    return team


async def get_team(root: Path, team_id: str) -> Team | None:
    for r in _read_rows(teams_path(root)):
        if r.get("id") == team_id:
            return Team(**r)
    return None


async def get_team_by_invite_token(root: Path, token: str) -> Team | None:
    token = token.strip()
    if not token:
        return None
    for r in _read_rows(teams_path(root)):
        if r.get("invite_token") == token:
            return Team(**r)
    return None


async def list_teams(root: Path) -> list[Team]:
    return [Team(**r) for r in _read_rows(teams_path(root))]


async def rename_team(root: Path, team_id: str, name: str) -> Team:
    async with auth_lock(root):
        rows = _read_rows(teams_path(root))
        for i, r in enumerate(rows):
            if r.get("id") == team_id:
                r["name"] = name.strip()
                team = Team(**r)
                rows[i] = team.model_dump(mode="json")
                atomic_write_json(teams_path(root), rows)
                return team
    raise TeamNotFoundError(team_id)


async def add_member(
    root: Path, team_id: str, user_id: str, *, set_active: bool = True
) -> tuple[User, Team]:
    """Join `user_id` to `team_id` — mutates both sides under one lock. Sets the
    user's `active_team_id` to this team when they had none (or when
    `set_active`). Idempotent: re-adding an existing member is a no-op."""
    async with auth_lock(root):
        urows = _read_rows(users_path(root))
        trows = _read_rows(teams_path(root))
        ui = next((i for i, r in enumerate(urows) if r.get("id") == user_id), None)
        ti = next((i for i, r in enumerate(trows) if r.get("id") == team_id), None)
        if ui is None:
            raise UserNotFoundError(user_id)
        if ti is None:
            raise TeamNotFoundError(team_id)

        ur, tr = urows[ui], trows[ti]
        if user_id not in tr.get("member_ids", []):
            tr.setdefault("member_ids", []).append(user_id)
        if team_id not in ur.get("team_ids", []):
            ur.setdefault("team_ids", []).append(team_id)
        if set_active or not ur.get("active_team_id"):
            ur["active_team_id"] = team_id

        user, team = User(**ur), Team(**tr)
        urows[ui] = user.model_dump(mode="json")
        trows[ti] = team.model_dump(mode="json")
        atomic_write_json(users_path(root), urows)
        atomic_write_json(teams_path(root), trows)
    return user, team
