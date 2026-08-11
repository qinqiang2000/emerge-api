"""Agent memory — HTTP twin of `forget_memory`.

Reading and writing notes needs no route: `_memory/` is ordinary files in the
team workspace, so `ws_read` / `ws_write` (and the in-session agent's own
Read/Write) already cover both directions. Retiring a note is the one operation
that is more than a file op — the body has to reach `_trash/` and the
`MEMORY.md` pointer has to go with it — so it gets a verb, and by the symmetry
invariant a route.

`DELETE` on the note as a resource: the project-scoped and team-scoped forms
are two paths rather than a `?scope=` flag, because the two directories are
genuinely different places and a typo'd flag should 404, not silently retire a
note in the wrong scope.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.workspace.memory import MemoryNoteError, forget_note


router = APIRouter(dependencies=[Depends(bind_workspace)])


def _forget(slug: str | None, note: str) -> dict:
    try:
        return forget_note(current_ws(), slug, note)
    except MemoryNoteError as e:
        msg = str(e)
        status = 404 if "no such note" in msg else 400
        raise HTTPException(
            status_code=status,
            detail={
                "error_code": "memory_note_not_found" if status == 404
                else "invalid_note_name",
                "error_message_en": msg,
            },
        )


@router.delete("/lab/projects/{slug}/memory/{note}")
async def delete_project_memory_note(slug: str, note: str) -> dict:
    """Retire one project-scoped note. Body → `_trash/`, index line dropped."""
    try:
        safe_slug(slug)
    except Exception:
        raise HTTPException(status_code=400, detail={
            "error_code": "invalid_slug", "error_message_en": "invalid slug"})
    return _forget(slug, note)


@router.delete("/lab/memory/{note}")
async def delete_team_memory_note(note: str) -> dict:
    """Retire one team-scoped note (facts that outlive a single project)."""
    return _forget(None, note)
