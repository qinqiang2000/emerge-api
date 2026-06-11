"""Audit-board render + notes routes (B4, 2026-06-11 audit-board plan).

GET /lab/projects/{slug}/audit/board-render
HTTP twin of the ``render_audit_board`` @tool (tool↔HTTP symmetry, CLAUDE.md):
the latest audit report composed into annotated per-doc images —
``{legend, images:[{doc, media_type, data_b64}], truncated}``. Coordinates die
inside the render layer; the payload is pixels + rule text only.

GET/PUT /lab/projects/{slug}/audit/board-notes
The user's freehand board annotations (excalidraw elements), persisted at
``audits/{run_id}/board_notes.json``. These two are RENDER-LAYER PERSISTENCE
and deliberately route-without-tool — same precedent as the locate routes
(INSIGHTS.md "field-source-grounding: source is TEXT, locate is a render
route"): an agent has no business round-tripping canvas element JSON, and the
symmetry invariant only enforces "@tool ⇒ route", so a route without a tool
needs no exempt entry. ``board_notes.json`` is USER annotation — unlike its
sibling ``report.json`` (a derived cache that re-running the audit replaces),
notes are never auto-deleted (绝不物理删除用户数据 red line).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.tools.audit_board_render import render_audit_board
from app.tools.audit_run import AuditError, read_audit_report
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import audits_dir

router = APIRouter(dependencies=[Depends(bind_workspace)])

# Cap on the serialized ``elements`` payload. Board notes are a handful of
# freehand strokes / text labels; anything megabyte-sized is a client bug
# (e.g. accidentally serializing the locked page images into the notes).
_MAX_NOTES_BYTES = 1_000_000


def _audit_envelope(e: AuditError) -> HTTPException:
    # audit_no_report = "the resource you asked about does not exist" → 404;
    # every other AuditError is a precondition failure → 400 (mirrors
    # routes/match.py's audit handlers, which only see the 400 family).
    return HTTPException(
        status_code=404 if e.error_code == "audit_no_report" else 400,
        detail={"error_code": e.error_code, "error_message_en": e.error_message_en},
    )


@router.get("/lab/projects/{slug}/audit/board-render")
async def get_audit_board_render(slug: str) -> dict:
    """Server-side composite of the latest audit report (universal fallback:
    any client that can show an image sees WHERE the evidence sits)."""
    safe_slug(slug)
    try:
        return await render_audit_board(current_ws(), slug)
    except AuditError as e:
        raise _audit_envelope(e)


@router.get("/lab/projects/{slug}/audit/board-notes")
async def get_audit_board_notes(slug: str) -> dict:
    """The user's board annotations for the LATEST audit run (v1: notes hang
    off the most recent run — the frontend warns when they came from an older
    one). No notes yet → empty elements, never a 404; no report at all → 404
    (there is no board to annotate)."""
    safe_slug(slug)
    try:
        report = await read_audit_report(current_ws(), slug)
    except AuditError as e:
        raise _audit_envelope(e)
    run_id = str(report.get("run_id") or "")
    notes_path = audits_dir(current_ws(), slug) / run_id / "board_notes.json"
    elements: list = []
    annotations: list = []
    if notes_path.is_file():
        try:
            blob = json.loads(notes_path.read_text(encoding="utf-8"))
            raw = blob.get("elements") if isinstance(blob, dict) else blob
            if isinstance(raw, list):
                elements = raw
            # D1 anchor sidecar — pre-D1 files simply lack the key → []
            raw_ann = blob.get("annotations") if isinstance(blob, dict) else None
            if isinstance(raw_ann, list):
                annotations = raw_ann
        except (OSError, json.JSONDecodeError):
            pass  # unreadable notes degrade to empty, never break board load
    return {"run_id": run_id, "elements": elements, "annotations": annotations}


class _BoardNotesBody(BaseModel):
    run_id: str
    elements: list
    # D1 (2026-06-12 doodle plan): per-element anchors {id, kind, doc, page,
    # rect, text?} derived from `elements` at save time. Render-layer
    # persistence only — rects are legal in this file and the digest (D2)
    # turns them into pure text before any agent sees them; this list must
    # never feed a @tool directly.
    annotations: list | None = None


@router.put("/lab/projects/{slug}/audit/board-notes")
async def put_audit_board_notes(slug: str, body: _BoardNotesBody) -> dict:
    safe_slug(slug)
    run_dir = audits_dir(current_ws(), slug) / body.run_id
    # A run_id is a single path component (au_xxx); anything separator-shaped
    # cannot name a run dir — refuse before touching the filesystem.
    if (
        not body.run_id
        or "/" in body.run_id
        or "\\" in body.run_id
        or body.run_id in (".", "..")
        or not run_dir.is_dir()
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "audit_run_not_found",
                "error_message_en": f"no audit run {body.run_id!r} for this project",
            },
        )
    payload = {
        "run_id": body.run_id,
        "elements": body.elements,
        "annotations": body.annotations or [],
    }
    # size cap covers the WHOLE payload (elements + annotations), not just
    # the elements list — anything megabyte-sized is a client bug either way.
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > _MAX_NOTES_BYTES:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "board_notes_too_large",
                "error_message_en": "board notes exceed 1MB — strip embedded "
                "binary/image data before saving",
            },
        )
    atomic_write_json(run_dir / "board_notes.json", payload)
    return {"run_id": body.run_id, "elements_saved": len(body.elements)}
