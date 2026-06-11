"""MCP Apps audit-board data plane — capability-token redemption (B5b).

NO auth dependency on purpose (mirrors `upload_token.redeem_router`): the
`ui://` board app runs in a sandboxed iframe inside Claude / Claude Desktop
with no session cookie or PAT — the HMAC token IS the auth (read-only, one
team workspace + slug, 30-min TTL, minted inside an authed tool call).

Deliberately route-without-tool (same legitimacy as `/locate-quotes`, see
INSIGHTS field-source-grounding): the payload carries locate RECTS, which
must never enter agent/model context. They flow HTTP → iframe render layer
only.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.tools.board_view import (
    BoardViewTokenError,
    build_board_view,
    verify_board_view_token,
)

redeem_router = APIRouter()


def _claims_or_401(token: str) -> dict:
    try:
        return verify_board_view_token(token)
    except BoardViewTokenError as exc:
        raise HTTPException(status_code=401, detail={
            "error_code": "board_view_token_invalid", "error_message_en": str(exc),
        })


@redeem_router.get("/lab/board-view/{token}")
async def get_board_view(token: str) -> dict:
    """Report + per-doc page counts + located rects, one payload."""
    claims = _claims_or_401(token)
    from app.tools.audit_run import AuditError
    try:
        return await build_board_view(Path(claims["ws"]), claims["slug"])
    except AuditError as e:
        raise HTTPException(status_code=404, detail={
            "error_code": e.error_code, "error_message_en": e.error_message_en,
        })


_IMAGE_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


@redeem_router.get("/lab/board-view/{token}/pages/{filename:path}/{page}")
async def get_board_view_page(token: str, filename: str, page: int) -> FileResponse:
    """Page raster for the board app — mirrors the authed docs `pages` route
    (PDF: cached render; image: page 1 = original bytes). Token-scoped to the
    slug: the iframe can only read pages of the project its capability names."""
    claims = _claims_or_401(token)
    import json as _json

    from app.api.routes._safety import safe_filename  # same sanitizer as docs routes
    from app.tools.docs import pdf_render_page
    from app.workspace.paths import doc_meta_path, doc_path

    ws, slug = Path(claims["ws"]), claims["slug"]
    not_found = HTTPException(status_code=404, detail={
        "error_code": "doc_not_found",
        "error_message_en": f"no renderable page {page} of '{filename}'",
    })
    try:
        safe_filename(filename)
        meta = _json.loads(doc_meta_path(ws, slug, filename).read_text())
        ext = str(meta.get("ext", "")).lower()
        if ext in _IMAGE_MEDIA:
            if page != 1:
                raise ValueError("page out of range")
            return FileResponse(doc_path(ws, slug, filename),
                                media_type=_IMAGE_MEDIA[ext])
        rendered = await pdf_render_page(ws, slug, filename, page=page)
    except HTTPException:
        raise
    except Exception:
        raise not_found
    return FileResponse(rendered, media_type="image/png")
