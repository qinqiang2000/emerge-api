"""Auth control-plane routes (Users & Teams, 2026-06-03).

NOT `@tool`s — auth is the control plane, like the locate/textlayer render
routes (the symmetry invariant only enforces tool⇒route, not the reverse). All
auth state is GLOBAL (cross-team), so these handlers use `settings.workspace_
root` directly, never `current_ws()`.

Browser channel: `request.session["uid"]` (signed cookie via SessionMiddleware).
Headless channel: bearer PAT minted at `POST /auth/me/tokens` (see deps.py).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import store, tokens
from app.auth.deps import current_superuser, current_user
from app.auth.models import User
from app.config import get_settings

router = APIRouter()


def _root() -> Path:
    return get_settings().workspace_root


def _err(status: int, code: str, msg: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "error_message_en": msg})


# --- signup / login / logout ------------------------------------------------

class _SignupBody(BaseModel):
    email: str
    password: str
    full_name: str = ""
    token: str  # team invite token


@router.post("/auth/signup")
async def signup(body: _SignupBody, request: Request) -> dict:
    root = _root()
    email = body.email.strip()
    if "@" not in email or not body.password:
        raise _err(400, "invalid_credentials", "email and password are required")
    team = await store.get_team_by_invite_token(root, body.token)
    if team is None:
        raise _err(400, "invalid_invite", "invite link is invalid or expired")
    try:
        user = await store.create_user(
            root, email=email, password=body.password, full_name=body.full_name.strip(),
        )
    except store.DuplicateEmailError:
        raise _err(409, "email_taken", "an account with this email already exists")
    user, _team = await store.add_member(root, team.id, user.id)
    request.session["uid"] = user.id
    return {"user": user.public(), "active_team": _team.public()}


class _LoginBody(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
async def login(body: _LoginBody, request: Request) -> dict:
    from app.auth.passwords import verify_password

    root = _root()
    user = await store.get_user_by_email(root, body.email)
    if user is None or not verify_password(body.password, user.password_hash):
        raise _err(401, "bad_login", "email or password is incorrect")
    request.session["uid"] = user.id
    return {"user": user.public()}


@router.post("/auth/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


# --- me ---------------------------------------------------------------------

async def _me_payload(root: Path, user: User) -> dict:
    teams = [t.public() for t in await store.list_teams(root) if t.id in user.team_ids]
    active = next((t for t in teams if t["id"] == user.active_team_id), None)
    return {"authenticated": True, "open_mode": False, "user": user.public(),
            "active_team": active, "teams": teams}


@router.get("/auth/me")
async def me(user: User | None = Depends(current_user)) -> dict:
    if user is None:  # open mode — no auth configured
        return {"authenticated": False, "open_mode": True, "user": None,
                "active_team": None, "teams": []}
    return await _me_payload(_root(), user)


class _UpdateMeBody(BaseModel):
    full_name: str | None = None
    display_name: str | None = None
    new_password: str | None = None


@router.patch("/auth/me")
async def update_me(body: _UpdateMeBody, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    updated = await store.update_user(
        _root(), user.id,
        full_name=body.full_name, display_name=body.display_name,
        new_password=body.new_password,
    )
    return {"user": updated.public()}


# --- personal access tokens (headless / cowork) -----------------------------

class _MintTokenBody(BaseModel):
    label: str = ""


@router.post("/auth/me/tokens")
async def mint_token(body: _MintTokenBody, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    plaintext, pat_id = await tokens.mint_pat(_root(), user.id, label=body.label)
    # reveal-once: the only time `token` is ever returned.
    return {"token": plaintext, "pat_id": pat_id, "label": body.label.strip()}


@router.get("/auth/me/tokens")
async def list_tokens(user: User = Depends(current_user)) -> list[dict]:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    return await tokens.list_pats(_root(), user.id)


@router.delete("/auth/me/tokens/{pat_id}")
async def revoke_token(pat_id: str, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    removed = await tokens.revoke_pat(_root(), pat_id, user.id)
    if not removed:
        raise _err(404, "token_not_found", "no such token")
    return {"ok": True}


# --- teams ------------------------------------------------------------------

@router.get("/auth/teams/{team_id}")
async def get_team(team_id: str, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    if team_id not in user.team_ids and not user.is_superuser:
        raise _err(403, "forbidden", "not a member of this team")
    root = _root()
    team = await store.get_team(root, team_id)
    if team is None:
        raise _err(404, "team_not_found", "no such team")
    members = [
        {"id": m.id, "email": m.email, "full_name": m.full_name, "display_name": m.display_name}
        for m in await store.list_users(root) if m.id in team.member_ids
    ]
    return {"team": team.public(), "members": members}


class _RenameTeamBody(BaseModel):
    name: str


@router.patch("/auth/teams/{team_id}")
async def rename_team(team_id: str, body: _RenameTeamBody, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    if team_id not in user.team_ids and not user.is_superuser:
        raise _err(403, "forbidden", "not a member of this team")
    if not body.name.strip():
        raise _err(400, "invalid_name", "team name must be non-empty")
    team = await store.rename_team(root=_root(), team_id=team_id, name=body.name)
    return {"team": team.public()}


class _SwitchTeamBody(BaseModel):
    team_id: str


@router.post("/auth/teams/switch")
async def switch_team(body: _SwitchTeamBody, user: User = Depends(current_user)) -> dict:
    if user is None:
        raise _err(401, "not_authenticated", "login required")
    if body.team_id not in user.team_ids and not user.is_superuser:
        raise _err(403, "forbidden", "not a member of this team")
    updated = await store.update_user(_root(), user.id, active_team_id=body.team_id)
    return {"user": updated.public()}


# --- superuser admin --------------------------------------------------------

class _CreateTeamBody(BaseModel):
    name: str


@router.post("/auth/admin/teams")
async def admin_create_team(body: _CreateTeamBody, su: User = Depends(current_superuser)) -> dict:
    if not body.name.strip():
        raise _err(400, "invalid_name", "team name must be non-empty")
    team = await store.create_team(_root(), name=body.name, created_by=su.id)
    return {"team": team.public()}


@router.get("/auth/admin/teams")
async def admin_list_teams(su: User = Depends(current_superuser)) -> list[dict]:
    return [t.public() for t in await store.list_teams(_root())]


@router.get("/auth/admin/users")
async def admin_list_users(su: User = Depends(current_superuser)) -> list[dict]:
    return [u.public() for u in await store.list_users(_root())]
