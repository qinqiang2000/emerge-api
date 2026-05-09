from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, File, Header, UploadFile
from fastapi.responses import JSONResponse

from app.api.routes._safety import safe_project_id
from app.config import get_settings
from app.provider import get_provider_for_model
from app.schemas.envelope import ErrorEnvelope
from app.schemas.schema_field import SchemaField
from app.security.keys import (
    get_keystore,
    key_hash_short,
    key_prefix_display,
    sha256_key,
)
from app.tools.extract import extract_bytes_with_schema
from app.workspace.paths import (
    parse_version_id,
    project_json_path,
    version_path,
)


router = APIRouter()
_log = logging.getLogger(__name__)
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_SUPPORTED_EXTS = {"pdf", "png", "jpg", "jpeg"}


class _AuthContext:
    __slots__ = ("project_id", "hash_hex", "plaintext_prefix")

    def __init__(self, project_id: str, hash_hex: str, plaintext_prefix: str) -> None:
        self.project_id = project_id
        self.hash_hex = hash_hex
        self.plaintext_prefix = plaintext_prefix


def _envelope(code: str, msg: str) -> dict[str, str]:
    return ErrorEnvelope(error_code=code, error_message_en=msg).model_dump()


def _error(status_code: int, code: str, msg: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=_envelope(code, msg))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_key(x_api_key: str | None) -> _AuthContext | JSONResponse:
    if not x_api_key:
        return _error(401, "missing_api_key", "X-API-Key header is required")
    settings = get_settings()
    store = get_keystore(settings.workspace_root)
    row = store.lookup(x_api_key)
    if row is None:
        return _error(401, "invalid_api_key", "API key is not recognized")
    return _AuthContext(
        project_id=row["project_id"],
        hash_hex=sha256_key(x_api_key),
        plaintext_prefix=key_prefix_display(x_api_key),
    )


@router.post("/v1/{project_id}/extract", response_model=None)
async def v1_extract(
    project_id: str,
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    try:
        safe_project_id(project_id)
    except Exception:
        return _error(400, "invalid_project_id", "invalid project_id")

    auth = _resolve_key(x_api_key)
    if isinstance(auth, JSONResponse):
        return auth
    if auth.project_id != project_id:
        return _error(404, "not_found", "no published API at this path")

    settings = get_settings()
    pj_path = project_json_path(settings.workspace_root, project_id)
    if not pj_path.exists():
        return _error(404, "not_found", "no published API at this path")
    project = json.loads(pj_path.read_text(encoding="utf-8"))
    active_vid = project.get("active_version_id")
    if not active_vid:
        return _error(404, "not_published", "project has no active version; run /publish first")
    n = parse_version_id(active_vid)
    if n is None:
        return _error(500, "active_version_corrupt", f"active_version_id={active_vid!r} is invalid")
    vp = version_path(settings.workspace_root, project_id, n)
    if not vp.exists():
        return _error(500, "active_version_missing", f"versions/{active_vid}.json is missing")

    version_blob = json.loads(vp.read_text(encoding="utf-8"))
    schema = [SchemaField(**field) for field in version_blob.get("schema", [])]
    if not schema:
        return _error(500, "active_version_corrupt", "frozen schema is empty")

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _SUPPORTED_EXTS:
        return _error(400, "unsupported_file_type", f"file extension {ext!r} not supported")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return _error(413, "payload_too_large", f"upload exceeds {_MAX_UPLOAD_BYTES} bytes")

    provider = get_provider_for_model(version_blob["model_id"])
    try:
        out = await extract_bytes_with_schema(
            content=content,
            filename=filename,
            schema=schema,
            provider=provider,
            model_id=version_blob["model_id"],
            params=version_blob.get("params") or {"temperature": 0.0},
        )
    except Exception as exc:
        _log.warning(
            "v1 extract failure for %s key_prefix=%s hash_short=%s: %s",
            project_id,
            auth.plaintext_prefix,
            key_hash_short(auth.hash_hex),
            exc,
        )
        return _error(502, "extract_failed", "extraction failed; see provider logs")

    try:
        get_keystore(settings.workspace_root).update_last_used(auth.hash_hex, _iso_now())
    except Exception:
        pass
    return out
