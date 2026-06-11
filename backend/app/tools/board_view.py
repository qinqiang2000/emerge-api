"""Capability-token data plane for the MCP Apps audit board (B5b).

The `ui://` board app runs in a sandboxed iframe inside Claude / Claude
Desktop. It cannot use the user's session cookie or PAT — like the presigned
upload URLs (`upload_url.py`), the token IS the capability: HMAC-signed,
scoped to one (team workspace, slug), short TTL. The agent's tool result
carries ONE such URL (plain text — red-line safe); the iframe redeems it for
the report + locate rects + page images.

Red line note: locate rects flow ONLY over this HTTP channel into the iframe
render layer. They never appear in any tool result / model context — exactly
the same posture as the web board's `/locate-quotes` route.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

from app.config import get_settings

_TTL_SECONDS = 30 * 60


class BoardViewTokenError(ValueError):
    """Token is malformed, tampered with, or expired."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: bytes) -> str:
    key = get_settings().secret_key.encode()
    return _b64(hmac.new(key, payload, hashlib.sha256).digest())


def mint_board_view_token(workspace: Path, slug: str) -> str:
    """One capability = read-only board view of one (team workspace, slug)
    for TTL seconds. `p` tags the purpose so an upload token can never be
    replayed as a view token (and vice versa)."""
    payload = json.dumps(
        {"p": "board-view", "ws": str(workspace.resolve()), "slug": slug,
         "exp": int(time.time()) + _TTL_SECONDS},
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def verify_board_view_token(token: str) -> dict[str, Any]:
    """Return the claims dict or raise BoardViewTokenError. Constant-time sig
    check; purpose + expiry checked after authenticity."""
    try:
        body_b64, sig = token.split(".", 1)
        payload = _unb64(body_b64)
    except Exception:
        raise BoardViewTokenError("malformed board-view token")
    if not hmac.compare_digest(_sign(payload), sig):
        raise BoardViewTokenError("board-view token signature mismatch")
    claims = json.loads(payload)
    if claims.get("p") != "board-view":
        raise BoardViewTokenError("not a board-view token")
    if int(claims.get("exp", 0)) < time.time():
        raise BoardViewTokenError("board-view token expired")
    return claims


def mint_board_view_url(workspace: Path, slug: str) -> str | None:
    """Absolute redeem URL, or None when EMERGE_PUBLIC_BASE_URL is unset
    (an iframe in a remote host can only reach an absolute public URL)."""
    base = get_settings().public_base_url.rstrip("/")
    if not base:
        return None
    return f"{base}/lab/board-view/{mint_board_view_token(workspace, slug)}"


async def build_board_view(workspace: Path, slug: str) -> dict[str, Any]:
    """Everything the iframe board needs, in one payload.

    Layout math (point→pixel scale, column flow) lives in the app itself —
    this payload ships report + per-doc page counts + located rects. Page
    image dimensions are read by the app from each `<img>`'s naturalWidth
    (same approach as the web board).
    """
    # Local imports: this module is imported by the routes layer at startup;
    # the heavy deps (locate, fitz via audit_run) stay lazy.
    from app.tools.audit_board_render import _locate_with_warm, _page_count, _resolve_doc
    from app.tools.audit_run import read_audit_report

    report = await read_audit_report(workspace, slug)
    checks = [c for c in (report.get("checks") or []) if isinstance(c, dict)]

    filenames: list[str] = []
    for fn in (report.get("group") or {}).values():
        if isinstance(fn, str) and fn not in filenames:
            filenames.append(fn)

    docs = [
        {
            "doc": fn,
            "ext": fn.rsplit(".", 1)[-1].lower() if "." in fn else "",
            "pages": _page_count(workspace, slug, fn),
        }
        for fn in filenames
    ]

    # Evidence → locate (warm self-heal, same path as render_audit_board).
    per_doc: dict[str, list[tuple[str, dict[str, Any]]]] = {fn: [] for fn in filenames}
    for i, check in enumerate(checks):
        for j, ev in enumerate(check.get("evidence") or []):
            if not isinstance(ev, dict):
                continue
            fn = _resolve_doc(str(ev.get("doc") or ""), filenames)
            if fn is None:
                continue
            per_doc[fn].append((
                f"{i}-{j}",
                {"page": ev.get("page"), "quote": str(ev.get("quote") or "")},
            ))

    locations: dict[str, dict[str, Any]] = {}
    for fn, entries in per_doc.items():
        if not entries:
            continue
        locs = await _locate_with_warm(
            workspace, slug, fn, [item for _, item in entries],
        )
        for (key, _item), loc in zip(entries, locs):
            if loc.status == "none" or not loc.rects:
                continue
            locations[key] = {
                "doc": fn,
                "page": loc.page,
                "rects": loc.rects,
                "status": loc.status,
            }

    return {"slug": slug, "report": report, "docs": docs, "locations": locations}
