"""Presigned doc download — the *outbound* half of the MCP data plane.

`upload_url.py` solved bytes going IN (client sandbox → server). This is the
mirror: bytes going OUT (server → whoever asked, browser or headless client).

Dogfood 2026-08-10 (prod, `海信日本-627人工标注`): the user asked the agent to
zip up 54 invoice+GT pairs. The agent did it — correctly, with Bash — and then
handed back `/root/emerge/backend/workspace/teams/.../_export/...zip`. The user
was in a browser. A server-side absolute path is not a delivery. On the next
project the agent instead went looking for a download route in its own source
(`grep attachments` → `docs.py` → `upload.py`), burned the whole turn budget,
and delivered nothing at all.

The gap was never "zip" — emerge already has Bash, so the agent can *produce*
anything. What it lacked was a way to hand the result across the server→user
boundary. Bash without this is ssh without scp: you can do all the work and
still not deliver it.

Same shape as the upload half, deliberately: control plane over MCP (the authed
`offer_download` tool mints a URL), data plane over plain HTTP (the bytes never
touch the model's token stream). The HMAC token IS the capability — scoped to
one resolved absolute path plus an expiry — so the redemption endpoint needs no
session and no PAT, and a browser can follow the link directly.

Containment is delegated wholesale to ``workspace_fs._safe_ws_path``: it
resolves symlinks and ``..`` before proving the target sits inside the caller's
team workspace, and it enforces the secret denylist (``.env`` / ``*.key`` /
``*.pem`` / ``*secret*`` / ``_keys*`` / ``_auth*``). That last part is
load-bearing, not decorative: in open mode ``current_ws()`` IS the real
workspace root, so without the denylist "帮我下载一下配置文件" would happily mint a
capability URL for the keystore.

## Inline preview (2026-08-10)

Agent-produced HTML (a report, a board render) is only useful if the user can
LOOK at it, and a .zip-style forced download is the wrong verb for a page. But
serving agent-written markup on the lab's own origin would hand it same-origin
access to the session cookie and every `/lab/*` route — an ingested document
that talks the agent into emitting a `fetch('/lab/...')` becomes account
takeover.

The obvious fix is a separate subdomain, and it is the weaker one: a sibling
origin still shares the registrable domain, so the day anything sets a
`domain=`-scoped cookie the isolation quietly evaporates — and it costs DNS +
a cert. Instead the inline response carries `Content-Security-Policy: sandbox`,
which drops the document into an **opaque** origin. Opaque is strictly stronger
than "a different name": it is same-origin with nothing at all, including
itself. No cookie access, no credentialed reads of `/lab/*`, no storage, and no
infrastructure to maintain.

`allow-scripts` is granted (charts and interactive reports are the point) but
`allow-same-origin` is NEVER granted — the pair together is self-defeating,
since a script in a same-origin sandbox can simply remove the sandbox.

Inline is opt-in per call AND allow-listed by extension: `_INLINE_TYPES` is
the full set. SVG is deliberately absent — it is an active document that can
carry script, and it is the one image type that would surprise a reader who
thinks "it's just a picture".
"""
from __future__ import annotations

import hmac
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app.config import get_settings

# Import the signing primitives rather than re-deriving them: both halves of the
# data plane must stay on one scheme and one secret, and a copy drifts. If a
# THIRD capability-token consumer ever appears, that's the signal to hoist these
# into their own module instead of importing across siblings.
from app.tools.upload_url import _b64, _sign, _unb64

# Longer than the upload TTL (15 min): an upload is redeemed by a script within
# seconds, but a download link is clicked by a human who may be at lunch, or
# forwarded to a colleague. Still bounded — a capability URL in a chat log
# should not stay live forever.
_TTL_SECONDS = 24 * 60 * 60

# Type claim, so an upload token can never be replayed as a download token (and
# vice versa) even though both are signed with the same secret.
_TOKEN_KIND = "dl"

# Extensions that may be rendered in the browser instead of saved, and the type
# each is served as. Anything absent here downloads, whatever the caller asked
# for. Note `.svg` is intentionally NOT here (active content dressed as an
# image) and neither is `.xml` (entity expansion / stylesheet tricks).
_INLINE_TYPES = {
    "html": "text/html; charset=utf-8",
    "htm": "text/html; charset=utf-8",
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "txt": "text/plain; charset=utf-8",
    "md": "text/plain; charset=utf-8",
    "csv": "text/plain; charset=utf-8",
    "json": "text/plain; charset=utf-8",
    "log": "text/plain; charset=utf-8",
}

# Applied to every inline response. `sandbox` with no `allow-same-origin` is the
# whole security story: the document lands in an opaque origin, so it cannot
# read `document.cookie`, cannot make credentialed same-origin requests to
# `/lab/*`, and gets no storage. `nosniff` keeps a text/plain note from being
# re-interpreted as markup; `no-referrer` stops the capability URL (which IS the
# credential) leaking through outbound requests the page makes.
_INLINE_HEADERS = {
    "Content-Security-Policy": "sandbox allow-scripts allow-popups",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def inline_type_for(filename: str) -> str | None:
    """Content type to serve ``filename`` as inline, or None if it must download."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _INLINE_TYPES.get(ext)


class DownloadTokenError(ValueError):
    """Token is malformed, tampered with, expired, or not a download token."""


def mint_token(target: Path, *, inline: bool = False) -> str:
    """One capability = one already-validated absolute path, for TTL seconds.

    ``target`` must already have passed ``_safe_ws_path`` — this function signs
    what it is given and performs no containment check of its own.

    ``inline`` rides INSIDE the signed payload rather than as a query parameter
    on purpose: disposition decides whether agent-written markup executes in the
    user's browser, so it must not be something a link recipient can flip.
    """
    claims: dict[str, Any] = {
        "t": _TOKEN_KIND, "p": str(target),
        "exp": int(time.time()) + _TTL_SECONDS,
    }
    if inline:
        claims["i"] = 1
    payload = json.dumps(claims, separators=(",", ":")).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def verify_token(token: str) -> dict[str, Any]:
    """Return the payload dict or raise. Signature first, then kind, then expiry
    — never leak validity through which check fired first."""
    try:
        body_b64, sig = token.split(".", 1)
        payload = _unb64(body_b64)
    except Exception:
        raise DownloadTokenError("malformed download token")
    if not hmac.compare_digest(_sign(payload), sig):
        raise DownloadTokenError("download token signature mismatch")
    claims = json.loads(payload)
    if claims.get("t") != _TOKEN_KIND:
        raise DownloadTokenError("not a download token")
    if int(claims.get("exp", 0)) < time.time():
        raise DownloadTokenError("download token expired")
    return claims


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """RFC 5987 disposition header.

    emerge project and doc names are routinely non-ASCII (`海信日本-627人工标注_导出.zip`).
    A bare `filename="..."` mangles those, so always emit the UTF-8 form
    alongside an ASCII-safe fallback for ancient clients.
    """
    ascii_fallback = filename.encode("ascii", "replace").decode("ascii").replace('"', "")
    kind = "inline" if inline else "attachment"
    return (
        f'{kind}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


def mint_download_url(
    workspace: Path, path: str, *, inline: bool = False,
) -> dict[str, Any]:
    """Validate ``path`` inside ``workspace`` and mint a capability URL for it.

    Shared by the `offer_download` MCP tool and its HTTP twin. Returns an
    ``{error_code, error_message_en}`` envelope rather than raising, matching
    every other tool-facing helper in this package.

    ``inline=True`` asks for a page the user opens rather than saves. It is
    downgraded (not refused) for any extension outside `_INLINE_TYPES`: the
    caller still gets a working link, and the response says what happened, so
    "please preview this zip" degrades to a download instead of an error.
    """
    # Imported here rather than at module scope: `workspace_fs` pulls in the
    # tool-body helpers, and this module is imported by the route layer.
    from app.tools.workspace_fs import WsPathError, _safe_ws_path

    # Unlike the upload half, a missing public base URL is NOT fatal here. An
    # upload is redeemed by a script in a foreign sandbox, which has nothing to
    # resolve a relative path against; a download is usually clicked in a
    # browser that is already on this origin. Hard-failing would make the whole
    # feature dead on arrival in any deployment that hasn't set the env var —
    # including local dev, where it isn't set and the browser reaches
    # /lab/download/... through the vite proxy perfectly well.
    base = get_settings().public_base_url.rstrip("/")
    try:
        target = _safe_ws_path(workspace, path)
    except WsPathError as exc:
        return {"error_code": "path_not_allowed", "error_message_en": str(exc)}
    if not target.exists():
        return {
            "error_code": "not_found",
            "error_message_en": f"no such file in this workspace: {path}",
        }
    if target.is_dir():
        return {
            "error_code": "is_a_directory",
            "error_message_en": (
                f"{path} is a directory — zip it first (Bash), then offer the "
                "archive"
            ),
        }
    served_inline = bool(inline) and inline_type_for(target.name) is not None
    out: dict[str, Any] = {
        "filename": target.name,
        "size_bytes": target.stat().st_size,
        "expires_in_seconds": _TTL_SECONDS,
        "download_url": (
            f"{base}/lab/download/{mint_token(target, inline=served_inline)}"
        ),
        "opens_in_browser": served_inline,
        # The agent needs this for the headless rendering contract (a CLI client
        # can read the file directly instead of fetching it).
        "server_path": str(target),
    }
    # Both conditions can hold at once (local dev previewing a zip), so collect
    # rather than assign — an overwrite here would silently drop one warning.
    notes: list[str] = []
    if inline and not served_inline:
        notes.append(
            f"{target.name} is not a previewable type — link downloads instead"
        )
    if not base:
        notes.append(
            "relative URL — fine for a browser already on this origin; set "
            "EMERGE_PUBLIC_BASE_URL if links must work outside it"
        )
    if notes:
        out["note"] = "; ".join(notes)
    return out
