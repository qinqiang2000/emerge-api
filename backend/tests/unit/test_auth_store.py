"""T1 — auth data model + FS store (Users & Teams milestone, 2026-06-03)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.auth import store
from app.auth.passwords import hash_password, verify_password
from app.auth.store import (
    DuplicateEmailError,
    TeamNotFoundError,
    UserNotFoundError,
)


# --- passwords --------------------------------------------------------------

def test_password_hash_roundtrip() -> None:
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2$")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_password_hash_is_salted() -> None:
    # same plaintext → different stored hashes (random salt)
    assert hash_password("x") != hash_password("x")


def test_verify_password_fails_closed_on_garbage() -> None:
    assert verify_password("x", "not-a-valid-hash") is False
    assert verify_password("x", "") is False


# --- users ------------------------------------------------------------------

async def test_create_and_get_user(workspace: Path) -> None:
    u = await store.create_user(
        workspace, email="Alice@Honor.com", password="pw", full_name="Alice"
    )
    assert u.id.startswith("u_")
    assert u.email == "alice@honor.com"  # normalized
    assert u.display_name == "Alice"  # defaults to full_name
    assert u.active_team_id is None

    by_id = await store.get_user(workspace, u.id)
    by_email = await store.get_user_by_email(workspace, "  ALICE@honor.com ")
    assert by_id is not None and by_id.id == u.id
    assert by_email is not None and by_email.id == u.id


async def test_duplicate_email_rejected(workspace: Path) -> None:
    await store.create_user(workspace, email="a@b.com", password="x")
    with pytest.raises(DuplicateEmailError):
        await store.create_user(workspace, email="A@B.com", password="y")


async def test_password_hash_never_plaintext(workspace: Path) -> None:
    u = await store.create_user(workspace, email="a@b.com", password="secret-pw")
    assert "secret-pw" not in u.password_hash
    assert verify_password("secret-pw", u.password_hash) is True
    # public projection drops the hash entirely
    assert "password_hash" not in u.public()


async def test_update_user_profile_and_password(workspace: Path) -> None:
    u = await store.create_user(workspace, email="a@b.com", password="old")
    u2 = await store.update_user(
        workspace, u.id, full_name="New Name", new_password="new"
    )
    assert u2.full_name == "New Name"
    assert verify_password("new", u2.password_hash) is True
    assert verify_password("old", u2.password_hash) is False


async def test_update_user_active_team_can_be_set_and_cleared(workspace: Path) -> None:
    u = await store.create_user(workspace, email="a@b.com", password="x")
    u2 = await store.update_user(workspace, u.id, active_team_id="t_abc")
    assert u2.active_team_id == "t_abc"
    u3 = await store.update_user(workspace, u.id, active_team_id=None)
    assert u3.active_team_id is None


async def test_update_missing_user_raises(workspace: Path) -> None:
    with pytest.raises(UserNotFoundError):
        await store.update_user(workspace, "u_nope", full_name="x")


async def test_superuser_flag_persists(workspace: Path) -> None:
    await store.create_user(workspace, email="root@x.com", password="x", is_superuser=True)
    fetched = await store.get_user_by_email(workspace, "root@x.com")
    assert fetched is not None and fetched.is_superuser is True
    users = await store.list_users(workspace)
    assert len(users) == 1


# --- teams ------------------------------------------------------------------

async def test_create_team_and_lookup(workspace: Path) -> None:
    creator = await store.create_user(workspace, email="root@x.com", password="x", is_superuser=True)
    t = await store.create_team(workspace, name="荣耀", created_by=creator.id)
    assert t.id.startswith("t_")
    assert t.invite_token
    assert t.member_ids == []  # creator is NOT auto-member
    assert t.created_by == creator.id

    assert (await store.get_team(workspace, t.id)).name == "荣耀"
    by_tok = await store.get_team_by_invite_token(workspace, f"  {t.invite_token} ")
    assert by_tok is not None and by_tok.id == t.id
    assert await store.get_team_by_invite_token(workspace, "bogus") is None


async def test_rename_team(workspace: Path) -> None:
    t = await store.create_team(workspace, name="old", created_by="u_x")
    t2 = await store.rename_team(workspace, t.id, "new")
    assert t2.name == "new"
    with pytest.raises(TeamNotFoundError):
        await store.rename_team(workspace, "t_nope", "x")


# --- membership -------------------------------------------------------------

async def test_add_member_updates_both_sides_and_sets_active(workspace: Path) -> None:
    t = await store.create_team(workspace, name="Honor", created_by="u_root")
    u = await store.create_user(workspace, email="dev@honor.com", password="x")
    assert u.active_team_id is None

    user, team = await store.add_member(workspace, t.id, u.id)
    assert u.id in team.member_ids
    assert t.id in user.team_ids
    assert user.active_team_id == t.id  # first team → becomes active

    # persisted on disk, not just returned
    refetch = await store.get_user(workspace, u.id)
    assert refetch is not None and refetch.team_ids == [t.id]


async def test_add_member_is_idempotent(workspace: Path) -> None:
    t = await store.create_team(workspace, name="Honor", created_by="u_root")
    u = await store.create_user(workspace, email="dev@honor.com", password="x")
    await store.add_member(workspace, t.id, u.id)
    user, team = await store.add_member(workspace, t.id, u.id)
    assert team.member_ids == [u.id]
    assert user.team_ids == [t.id]


async def test_add_member_missing_team_or_user_raises(workspace: Path) -> None:
    u = await store.create_user(workspace, email="a@b.com", password="x")
    with pytest.raises(TeamNotFoundError):
        await store.add_member(workspace, "t_nope", u.id)
    t = await store.create_team(workspace, name="x", created_by="u_root")
    with pytest.raises(UserNotFoundError):
        await store.add_member(workspace, t.id, "u_nope")


async def test_second_team_does_not_steal_active(workspace: Path) -> None:
    t1 = await store.create_team(workspace, name="A", created_by="u_root")
    t2 = await store.create_team(workspace, name="B", created_by="u_root")
    u = await store.create_user(workspace, email="a@b.com", password="x")
    await store.add_member(workspace, t1.id, u.id)
    # joining a 2nd team without set_active keeps the first as active
    user, _ = await store.add_member(workspace, t2.id, u.id, set_active=False)
    assert user.active_team_id == t1.id
    assert set(user.team_ids) == {t1.id, t2.id}
