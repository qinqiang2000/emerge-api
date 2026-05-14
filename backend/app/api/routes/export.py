from __future__ import annotations

import json
import re

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.exports.bundler import BundleVersionMissingError, build_zip_bundle
from app.schemas.envelope import ErrorEnvelope
from app.workspace.paths import parse_version_id, project_json_path


router = APIRouter()
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _envelope(code: str, msg: str) -> dict[str, str]:
    return ErrorEnvelope(error_code=code, error_message_en=msg).model_dump()


def _error(status_code: int, code: str, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_envelope(code, msg))


def _safe_filename(name: str, version_id: str) -> str:
    base = _FILENAME_SAFE.sub("-", name).strip("-_") or "project"
    return f"{base}-{version_id}.zip"


@router.get("/lab/projects/{slug}/export", response_model=None)
async def lab_export(slug: str, version: int | None = Query(default=None, ge=1)):
    try:
        safe_slug(slug)
    except Exception:
        return _error(400, "invalid_slug", "invalid slug")

    workspace = get_settings().workspace_root
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

    filename = _safe_filename(project_blob.get("name", "project"), f"v{n}")
    return StreamingResponse(
        iter([blob]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
