"""Presigned upload — HTTP twin of `request_upload_url` + the data-plane
redemption endpoint. See `app/tools/upload_url.py` for the why (MCP has no
binary data plane; control over MCP, bytes over HTTP).

Two routers on purpose:
- `router` (authed, bind_workspace): mint URLs — the symmetry twin.
- `redeem_router` (NO auth dependency): `POST /lab/upload/{token}` — the
  HMAC token IS the auth (scoped team+slug+filename+TTL, minted by an authed
  caller). Adding session/PAT auth here would defeat the design: the client
  sandbox holding the bytes has no credential, only the capability URL.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from app.auth.deps import bind_workspace, current_ws
from app.tools.docs import upload_doc
from app.tools.upload_url import (
    MAX_UPLOAD_BYTES,
    UploadTokenError,
    mint_upload_urls,
    verify_token,
)

router = APIRouter(dependencies=[Depends(bind_workspace)])
redeem_router = APIRouter()


@router.post("/lab/upload-urls")
async def post_upload_urls(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    slug = body.get("slug")
    filenames = body.get("filenames")
    if not isinstance(slug, str) or not isinstance(filenames, list) or not filenames:
        raise HTTPException(status_code=400, detail={
            "error_code": "bad_request",
            "error_message_en": "body must be {slug: str, filenames: [str, ...]}",
        })
    out = mint_upload_urls(current_ws(), slug, [str(f) for f in filenames])
    if "error_code" in out:
        raise HTTPException(status_code=400, detail=out)
    return out


@redeem_router.post("/lab/upload/{token}")
async def redeem_upload(token: str, request: Request) -> dict[str, Any]:
    """Accept raw bytes (`--data-binary`) for a minted capability. Funnels
    through `upload_doc`, so magic-byte sniffing / filename slug+dedupe /
    sidecar invariants all hold. Replay within TTL dedupes, never overwrites."""
    try:
        claims = verify_token(token)
    except UploadTokenError as exc:
        raise HTTPException(status_code=403, detail={
            "error_code": "upload_token_invalid", "error_message_en": str(exc),
        })
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail={
            "error_code": "empty_body",
            "error_message_en": "POST the file bytes with --data-binary @file",
        })
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail={
            "error_code": "payload_too_large",
            "error_message_en": f"max upload is {MAX_UPLOAD_BYTES} bytes",
        })
    from pathlib import Path

    ws = Path(claims["ws"])
    if not (ws / claims["slug"] / "project.json").exists():
        raise HTTPException(status_code=404, detail={
            "error_code": "project_not_found",
            "error_message_en": f"project '{claims['slug']}' no longer exists",
        })
    try:
        meta = await upload_doc(ws, claims["slug"], data, claims["fn"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={
            "error_code": "unsupported_payload", "error_message_en": str(exc),
        })
    return {"filename": meta["filename"], "page_count": meta["page_count"],
            "sha256": meta["sha256"]}
