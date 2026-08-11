"""Publish-bundle export — the *authed* file-out path.

emerge has two ways to hand a file to a user, and they are not redundant:

| | this route | `download.py` / `offer_download` |
|---|---|---|
| auth | session / PAT, per request | HMAC capability token IS the auth |
| bytes | generated per call, never on disk | an existing file, streamed |
| audience | the export button in Publish | anything the agent produces |
| lifetime | none — nothing is stored | 24 h token, path fixed at mint |

Folding this route into `offer_download` was considered (2026-08-11) and
rejected on three counts. It would (1) downgrade an authenticated, session-gated
download to a 24-hour bearer-token URL that outlives the click and survives
being pasted into a chat log — for a bundle containing the project's schema and
model config; (2) require *materialising* the zip on disk purely to have
something to mint a token for, turning a stateless GET into per-click garbage in
`_export/`; and (3) turn one `<a href>` into a mint-then-redirect round trip.
DRY is not the axis these differ on. The one genuinely shared noun — RFC 5987
filename encoding — IS shared, via `content_disposition`.

Nor is `FileResponse` reachable here: there is no file. `build_zip_bundle`
returns bytes assembled from four small text members (schema.json,
version.json, curl_example.sh, README.md), so a real project's bundle is
kilobytes. The "reads whole bundles into RAM" concern that motivated this
revisit applies to `offer_download`'s targets (a 9.7 MB `docs.zip` was observed
in prod), not to this route.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Query
from app.auth.deps import bind_workspace, current_ws
from fastapi.responses import JSONResponse, Response

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.exports.bundler import BundleVersionMissingError, build_zip_bundle
from app.schemas.envelope import ErrorEnvelope
from app.tools.download_url import content_disposition
from app.workspace.paths import parse_version_id, project_json_path


router = APIRouter(dependencies=[Depends(bind_workspace)])

# Deliberately a DENYLIST, not the old `[^A-Za-z0-9_.-]` allowlist. Non-ASCII is
# the normal case here (`振兴_20260707`), and stripping it collapsed every
# Chinese-named project to the same `project-vN.zip`. What actually has to go is
# what could confuse a filesystem or an HTTP header: path separators, the
# Windows-reserved set, and control characters. Everything else is carried
# through by `content_disposition`'s RFC 5987 `filename*=UTF-8''…` form.
_FILENAME_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]+')


def _envelope(code: str, msg: str) -> dict[str, str]:
    return ErrorEnvelope(error_code=code, error_message_en=msg).model_dump()


def _error(status_code: int, code: str, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_envelope(code, msg))


def _bundle_filename(name: str, version_id: str) -> str:
    base = _FILENAME_UNSAFE.sub("-", name).strip("-_ .") or "project"
    return f"{base}-{version_id}.zip"


@router.get("/lab/projects/{slug}/export", response_model=None)
async def lab_export(slug: str, version: int | None = Query(default=None, ge=1)):
    try:
        safe_slug(slug)
    except Exception:
        return _error(400, "invalid_slug", "invalid slug")

    workspace = current_ws()
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        return _error(404, "not_found", "project not found")

    project_blob = json.loads(pj.read_text(encoding="utf-8"))
    if version is None:
        active_vid = project_blob.get("active_version_id")
        if not active_vid:
            return _error(404, "not_published", "project has no active version; run /publish first")
        n = parse_version_id(active_vid)
        if n is None:
            return _error(500, "active_version_corrupt", f"active_version_id={active_vid!r} is invalid")
    else:
        n = version

    # Latest `published_id` (if any) is the artifact the curl example will
    # call against; fall back to a placeholder when nothing's been frozen
    # yet (the export still ships a usable README/curl scaffold).
    published_ids = project_blob.get("published_ids") or []
    latest_pub_id = published_ids[-1] if isinstance(published_ids, list) and published_ids else None

    try:
        blob = build_zip_bundle(
            workspace=workspace,
            slug=slug,
            version_n=n,
            published_id=latest_pub_id,
        )
    except BundleVersionMissingError:
        return _error(404, "version_not_found", f"versions/v{n}.json does not exist")

    filename = _bundle_filename(project_blob.get("name", "project"), f"v{n}")
    # Plain `Response`, NOT `StreamingResponse(iter([blob]))` and NOT
    # `download.py`'s `FileResponse`. Both alternatives were considered and are
    # worse here — see this module's docstring for why. The short version: the
    # bytes are *generated*, never on disk, and they are kilobytes. Wrapping one
    # in-memory chunk in a streaming response bought no memory back and cost the
    # `Content-Length` header, so browsers downloaded the bundle chunked with no
    # size and no progress bar.
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(filename)},
    )
