"""FastAPI auth dependencies + the per-team workspace binder.

Two operating modes, switched by `store.auth_configured` (= "does any user
exist yet"):

- **Open mode** (no users): `current_user` → None, `bind_workspace` → the flat
  `workspace_root`. Identical to the pre-tenancy behaviour, so the existing
  test suite and a fresh un-bootstrapped install both just work, no auth.
- **Tenant mode** (≥1 user): auth is enforced on every `/lab/*` route via the
  router-level `dependencies=[Depends(bind_workspace)]`; the effective
  workspace becomes `workspace_root/teams/{active_team_id}`.

`current_user` is **dual-channel** (同事精神 / `MEMORY:priorities-efficiency-
experience-over-security`): a headless client sends `Authorization: Bearer
<pat>`; a browser carries the signed session cookie. Both resolve to the same
`User`, so the UI is fully replaceable by Claude Code / curl.

The resolved workspace is stashed in a `ContextVar` by `bind_workspace` (a
router-level dependency) and read back by `current_ws()` inside handlers — this
keeps the 92 lab endpoints free of per-signature churn while still resolving the
tenant explicitly (handlers pass `current_ws()` down to tools by value, never a
hidden thread-crossing global).
"""

from __future__ import annotations

import contextvars
from pathlib import Path

from fastapi import Depends, HTTPException, Request

from app.auth import store
from app.auth.models import User
from app.auth.tokens import verify_pat
from app.config import get_settings
from app.workspace.paths import team_workspace_dir

_TEAM_HEADER = "X-Emerge-Team"

# Request-scoped effective workspace. Per-request asyncio Tasks each get their
# own copied context, so a `.set()` in one request never leaks into another.
_ws_var: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "emerge_effective_ws", default=None
)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"error_code": "not_authenticated", "error_message_en": "login required"},
    )


async def current_user(request: Request) -> User | None:
    """Resolve the caller. None in open mode; raises 401 in tenant mode when no
    valid credential is present. Bearer PAT wins over the session cookie."""
    root = get_settings().workspace_root
    if not await store.auth_configured(root):
        return None  # open mode — no auth

    # 1) headless: Authorization: Bearer <pat>
    authz = request.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        uid = await verify_pat(root, authz[len("Bearer "):].strip())
        if uid:
            user = await store.get_user(root, uid)
            if user:
                return user

    # 2) browser: signed session cookie
    uid = request.session.get("uid")
    if uid:
        user = await store.get_user(root, uid)
        if user:
            return user

    raise _unauthorized()


async def current_superuser(user: User | None = Depends(current_user)) -> User:
    if user is None or not user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail={"error_code": "forbidden", "error_message_en": "superuser only"},
        )
    return user


async def _resolve_team_workspace(request: Request, user: User | None) -> Path:
    root = get_settings().workspace_root
    if user is None:
        return root  # open mode → flat root
    tid = user.active_team_id
    override = request.headers.get(_TEAM_HEADER)
    if override and (user.is_superuser or override in user.team_ids):
        tid = override
    if not tid:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "no_active_team", "error_message_en": "user has no active team"},
        )
    # The dir is named by the team's slug, not its id (human-readable spine).
    # Resolve the row to get the slug; fall back to id only if a pre-migration
    # row hasn't been backfilled yet (`migrate_team_dirs` normally guarantees it).
    team = await store.get_team(root, tid)
    if team is None:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "no_active_team", "error_message_en": "active team not found"},
        )
    return team_workspace_dir(root, team.slug or team.id)


async def bind_workspace(
    request: Request, user: User | None = Depends(current_user)
) -> Path:
    """Router-level dependency: resolve + stash the effective workspace. Used as
    a side-effecting `dependencies=[...]` entry; handlers read `current_ws()`."""
    ws = await _resolve_team_workspace(request, user)
    _ws_var.set(ws)
    return ws


def current_ws() -> Path:
    """The effective workspace for the in-flight request. Falls back to the flat
    root when unbound (e.g. a route that didn't go through `bind_workspace`, or
    a non-request context) — which is the correct open-mode value."""
    ws = _ws_var.get()
    return ws if ws is not None else get_settings().workspace_root
