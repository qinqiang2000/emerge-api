"""Recycle bin — list what was deleted, put it back.

Trash is workspace-scoped, not project-scoped: a deleted *project* lives there
too, so these routes take no `slug`. In tenant mode `current_ws()` resolves to
the team dir, so one team never sees another's bin.

Why this exists as a real surface rather than "go look in `_trash/`": every
delete path tells the user their data is recoverable for 14 days, and a promise
with no way to act on it is not a promise. The agent's own filesystem tools
hide `_` -prefixed dirs (`workspace_fs._HIDDEN_PREFIXES`), so chat could not
reach the bin either without these.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import bind_workspace, current_ws
from app.workspace.trash import TrashError, list_trash, restore_from_trash


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/trash")
async def get_trash() -> list[dict]:
    """Everything recoverable in this workspace, newest first. Rows carry
    `restorable: false` (with a `blocked_reason`) when the origin is occupied
    again or the entry predates the delete manifest — those still list, so the
    user can go handle them by hand instead of concluding the data is gone."""
    return list_trash(current_ws())


@router.post("/lab/trash/{entry}/restore")
async def post_restore_trash(entry: str) -> dict:
    """Replay one entry's manifest, putting every member back where it came
    from. All-or-nothing: 409 naming the collision if any origin is occupied,
    or if the project that owned the item no longer exists."""
    try:
        return restore_from_trash(current_ws(), entry)
    except TrashError as e:
        msg = str(e)
        if "no such trash entry" in msg or "invalid trash entry" in msg:
            raise HTTPException(status_code=404, detail={"error_code": "trash_entry_not_found"})
        raise HTTPException(
            status_code=409,
            detail={"error_code": "restore_blocked", "error_message_en": msg},
        )
