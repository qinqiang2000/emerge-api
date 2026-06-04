"""Agent-facing version history — log / diff / restore over the per-workspace
git repo (`app.workspace.history`).

The colleague spirit (CLAUDE.md): the version timeline is reachable from chat,
not just a background safety net. A customer can ask "what changed between these
two versions?" or "restore the schema to yesterday" and the agent drives it —
the same capability is exposed over HTTP + MCP (three-form symmetry).

Thin async wrappers: the git wrapper is synchronous subprocess work, so each
call hops to a worker thread. `slug` scopes to a project subtree; omit it for
the whole team workspace.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.workspace import history as _history


# A diff can be huge (binary docs, big schemas). Cap what we hand the agent /
# wire so a restore-worthy textual diff stays readable; `truncated` signals more.
_MAX_DIFF_CHARS = 20_000


async def history_log(
    workspace: Path, *, slug: str | None = None, limit: int = 30
) -> dict[str, Any]:
    """Version timeline, newest first. `slug` → just that project's history."""
    entries = await asyncio.to_thread(_history.log, workspace, path=slug, limit=limit)
    return {
        "scope": slug or "workspace",
        "count": len(entries),
        "versions": [
            {"ref": e["short"], "date": e["date"], "message": e["message"]}
            for e in entries
        ],
    }


async def history_diff(
    workspace: Path,
    *,
    ref_a: str,
    ref_b: str | None = None,
    slug: str | None = None,
) -> dict[str, Any]:
    """What changed. `ref_b` omitted → `ref_a` vs the current state."""
    text = await asyncio.to_thread(
        _history.diff, workspace, ref_a, ref_b, path=slug
    )
    truncated = len(text) > _MAX_DIFF_CHARS
    return {
        "a": ref_a,
        "b": ref_b or "current",
        "scope": slug or "workspace",
        "truncated": truncated,
        "diff": text[:_MAX_DIFF_CHARS],
    }


async def history_restore(
    workspace: Path, *, ref: str, slug: str | None = None
) -> dict[str, Any]:
    """Restore the team workspace (or `slug` project) to its state at `ref`. The
    restore is itself a new version (forward-moving, reversible)."""
    new = await asyncio.to_thread(_history.restore, workspace, ref, path=slug)
    if new is None:
        return {
            "ok": False,
            "error": {
                "error_code": "restore_failed",
                "error_message_en": f"could not restore {ref} (unknown ref, or nothing changed)",
            },
        }
    return {
        "ok": True,
        "restored_from": ref,
        "scope": slug or "workspace",
        "new_version": new[:12],
    }
