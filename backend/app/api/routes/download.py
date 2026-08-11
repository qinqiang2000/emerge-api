"""Presigned download — HTTP twin of `offer_download` + the data-plane
redemption endpoint. See `app/tools/download_url.py` for the why (Bash without
an outbound channel is ssh without scp).

Two routers, mirroring `upload_token.py`:
- `router` (authed, bind_workspace): mint URLs — the symmetry twin.
- `redeem_router` (NO auth dependency): `GET /lab/download/{token}` — the HMAC
  token IS the auth (one resolved path + TTL, minted by an authed caller).
  Adding session auth here would break the point: the link must be followable
  by a plain browser click, and by a headless client that holds the URL and no
  cookie.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.deps import bind_workspace, current_ws
from app.tools.download_url import (
    DownloadTokenError,
    content_disposition,
    mint_download_url,
    verify_token,
)

router = APIRouter(dependencies=[Depends(bind_workspace)])
redeem_router = APIRouter()


@router.post("/lab/download-urls")
async def post_download_urls(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail={
            "error_code": "bad_request",
            "error_message_en": "body must be {path: str} relative to the workspace",
        })
    out = mint_download_url(current_ws(), path)
    if "error_code" in out:
        raise HTTPException(status_code=400, detail=out)
    return out


@redeem_router.get("/lab/download/{token}", response_model=None)
async def redeem_download(token: str) -> FileResponse:
    """Stream the bytes for a minted capability.

    `FileResponse` streams from disk — deliberately not `export.py`'s
    `iter([blob])`, which materialises the whole archive in memory. Export
    bundles from a real project run tens of MB.
    """
    try:
        claims = verify_token(token)
    except DownloadTokenError as exc:
        raise HTTPException(status_code=403, detail={
            "error_code": "download_token_invalid", "error_message_en": str(exc),
        })
    target = Path(claims["p"])
    # Re-check at redemption: the token proves someone was authorised to offer
    # this path, not that the file still exists (it may have been trashed, or
    # the project renamed, between minting and the click).
    if not target.is_file():
        raise HTTPException(status_code=404, detail={
            "error_code": "not_found",
            "error_message_en": "the file this link pointed at no longer exists",
        })
    return FileResponse(
        target,
        media_type="application/octet-stream",
        headers={"Content-Disposition": content_disposition(target.name)},
    )
