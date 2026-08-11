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
    _INLINE_HEADERS,
    DownloadTokenError,
    content_disposition,
    inline_type_for,
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
            "error_message_en": "body must be {path: str, inline?: bool}",
        })
    out = mint_download_url(current_ws(), path, inline=bool(body.get("inline")))
    if "error_code" in out:
        raise HTTPException(status_code=400, detail=out)
    return out


@redeem_router.get("/lab/download/{token}", response_model=None)
async def redeem_download(token: str) -> FileResponse:
    """Stream the bytes for a minted capability.

    `FileResponse` streams from disk, which is what the targets here need: the
    first prod project to use this had the agent build it a 166 MB `docs.zip`.
    (`export.py` is NOT the same case and deliberately does not do this — its
    bytes are generated, kilobyte-sized, and never on disk. See its docstring.)
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
    # `inline` is re-derived from the extension, not trusted from the claim
    # alone: the claim says what was INTENDED, `inline_type_for` says what is
    # SAFE. Both must agree, so a token minted before an extension left the
    # allow-list can never resurrect inline rendering for it.
    media_type = inline_type_for(target.name) if claims.get("i") else None
    if media_type is None:
        return FileResponse(
            target,
            media_type="application/octet-stream",
            headers={"Content-Disposition": content_disposition(target.name)},
        )
    return FileResponse(
        target,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition(target.name, inline=True),
            # Opaque-origin sandbox — the entire reason inline is allowed at
            # all. See app/tools/download_url.py's module docstring.
            **_INLINE_HEADERS,
        },
    )
