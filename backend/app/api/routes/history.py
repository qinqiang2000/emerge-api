"""Version history routes — the HTTP form of the `history_*` tools (three-form
symmetry: every lab action reachable from a CLI client, not just the in-session
agent). Thin delegates to `app.tools.history`; workspace bound per-team by
`bind_workspace` and read via `current_ws()`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import bind_workspace, current_ws
from app.tools import history as history_mod

router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/history")
async def get_history(slug: str | None = None, limit: int = 30) -> dict:
    """Version timeline, newest first. `slug` scopes to one project."""
    return await history_mod.history_log(current_ws(), slug=slug, limit=limit)


@router.get("/lab/history/diff")
async def get_history_diff(a: str, b: str | None = None, slug: str | None = None) -> dict:
    """Diff `a`→`b` (or `a`→current when `b` omitted). `slug` scopes the diff."""
    return await history_mod.history_diff(current_ws(), ref_a=a, ref_b=b, slug=slug)


class _RestoreBody(BaseModel):
    ref: str
    slug: str | None = None


@router.post("/lab/history/restore")
async def post_history_restore(body: _RestoreBody) -> dict:
    """Restore to `ref` (a new, reversible version). `slug` scopes to a project."""
    return await history_mod.history_restore(current_ws(), ref=body.ref, slug=body.slug)
