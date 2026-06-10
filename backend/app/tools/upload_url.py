"""Presigned doc upload — the MCP bus's missing *data plane*.

MCP tool calls move through the model's token stream, so a binary doc can
never ride a tool argument (a 3 MB PDF would be ~4 MB of base64 the model
must literally generate token by token). True filesystem protocols (NFS/scp)
have a separate data plane; MCP does not — its resources only flow
server→client. Dogfood 2026-06-10: a Cowork user attached 4 PDFs and asked
to put them in a project; the files lived in the *client's* sandbox, the
server had no ingestion path, and the agent flailed (`ws_move` correctly
refused — both its endpoints are server-side).

The fix is the S3/GCS pattern: **control plane over MCP, data plane over
plain HTTP**. The authed `request_upload_url` tool mints short-lived
HMAC-signed one-shot URLs; the agent then `curl --data-binary`s the bytes
from its own sandbox to `POST /lab/upload/{token}` — zero bytes through the
model context, no credential ever shown to the agent (the token IS the
capability, scoped to one team + slug + filename + expiry).

Redemption funnels through `tools.docs.upload_doc`, so every invariant
(magic-byte sniff, filename slug + dedupe, sidecar) holds exactly as for a
browser upload. Stateless tokens can't be single-use; the 15-min TTL plus
upload_doc's dedupe (replay lands as "name (1).pdf", never an overwrite)
bounds the damage.
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

_TTL_SECONDS = 15 * 60
# Binary docs (scanned PDFs) run tens of MB; text uploads elsewhere cap much
# lower but this is the bulk-data path.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class UploadTokenError(ValueError):
    """Token is malformed, tampered with, or expired."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: bytes) -> str:
    key = get_settings().secret_key.encode()
    return _b64(hmac.new(key, payload, hashlib.sha256).digest())


def mint_token(workspace: Path, slug: str, filename: str) -> str:
    """One capability = one (team workspace, slug, filename) for TTL seconds."""
    payload = json.dumps(
        {"ws": str(workspace), "slug": slug, "fn": filename,
         "exp": int(time.time()) + _TTL_SECONDS},
        separators=(",", ":"),
    ).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def verify_token(token: str) -> dict[str, Any]:
    """Return the payload dict or raise UploadTokenError. Constant-time sig
    check; expiry checked after authenticity (don't leak validity timing)."""
    try:
        body_b64, sig = token.split(".", 1)
        payload = _unb64(body_b64)
    except Exception:
        raise UploadTokenError("malformed upload token")
    if not hmac.compare_digest(_sign(payload), sig):
        raise UploadTokenError("upload token signature mismatch")
    claims = json.loads(payload)
    if int(claims.get("exp", 0)) < time.time():
        raise UploadTokenError("upload token expired")
    return claims


def mint_upload_urls(
    workspace: Path, slug: str, filenames: list[str],
) -> dict[str, Any]:
    """Mint one presigned URL per filename. Shared by the MCP tool and its
    HTTP twin. Requires `EMERGE_PUBLIC_BASE_URL` (the data plane needs an
    absolute URL the client sandbox can reach)."""
    base = get_settings().public_base_url.rstrip("/")
    if not base:
        return {
            "error_code": "public_base_url_not_configured",
            "error_message_en": (
                "EMERGE_PUBLIC_BASE_URL is not set — presigned uploads need a "
                "public URL the client can POST bytes to"
            ),
        }
    if not (workspace / slug / "project.json").exists():
        return {
            "error_code": "project_not_found",
            "error_message_en": f"no project '{slug}' in this workspace",
        }
    uploads = []
    for fn in filenames:
        url = f"{base}/lab/upload/{mint_token(workspace, slug, fn)}"
        uploads.append({
            "filename": fn,
            "upload_url": url,
            "curl": f"curl -sS -X POST --data-binary @'{fn}' '{url}'",
        })
    return {"slug": slug, "expires_in_seconds": _TTL_SECONDS, "uploads": uploads}
