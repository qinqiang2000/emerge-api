from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, Form, Header, Query, UploadFile
from fastapi.responses import JSONResponse

from app.api.routes._safety import safe_published_id, safe_slug
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
from app.tools.publish import contract_diff as contract_diff_impl
from app.tools.publish import readiness_check as readiness_check_impl
from app.workspace.paths import (
    parse_version_id,
    project_json_path,
    published_path,
    version_path,
)


router = APIRouter()
_log = logging.getLogger(__name__)
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_SUPPORTED_EXTS = {"pdf", "png", "jpg", "jpeg"}


class _AuthContext:
    """Per-call auth state after `_resolve_key` accepts a key.

    Post-slug-transparency keys are user-scoped (not project-scoped). One key
    calls *any* `published_id` the user wants — emerge is staging, so the
    auth model deliberately mirrors what production deployments will use."""

    __slots__ = ("user_id", "hash_hex", "plaintext_prefix")

    def __init__(self, user_id: str, hash_hex: str, plaintext_prefix: str) -> None:
        self.user_id = user_id
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
        user_id=str(row.get("user_id") or "default"),
        hash_hex=sha256_key(x_api_key),
        plaintext_prefix=key_prefix_display(x_api_key),
    )


@router.post("/v1/extract", response_model=None)
async def v1_extract(
    file: UploadFile = File(...),
    published_id: str = Form(...),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    """Public extract endpoint. URL is stable; `published_id` is a form field.

    Reads the frozen artifact at `_published/{published_id}.json` directly —
    schema, model_id, params are all self-contained, so the endpoint keeps
    working after the source project is renamed or deleted. This mirrors how
    `published_id` will eventually be synced to a production deployment.
    """
    try:
        safe_published_id(published_id)
    except Exception:
        return _error(400, "invalid_published_id", "invalid published_id")

    auth = _resolve_key(x_api_key)
    if isinstance(auth, JSONResponse):
        return auth

    settings = get_settings()
    pub_path = published_path(settings.workspace_root, published_id)
    if not pub_path.exists():
        return _error(404, "not_found", "no published API at this id")

    try:
        blob: dict[str, Any] = json.loads(pub_path.read_text(encoding="utf-8"))
    except Exception:
        return _error(500, "published_corrupt", "frozen artifact is unreadable")

    schema = [SchemaField(**f) for f in blob.get("schema", [])]
    if not schema:
        return _error(500, "published_corrupt", "frozen schema is empty")

    filename = file.filename or ""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _SUPPORTED_EXTS:
        return _error(400, "unsupported_file_type", f"file extension {ext!r} not supported")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return _error(413, "payload_too_large", f"upload exceeds {_MAX_UPLOAD_BYTES} bytes")

    model_id = blob.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        return _error(500, "published_corrupt", "frozen artifact has no model_id")
    provider_name = blob.get("provider")
    provider = get_provider_for_model(
        model_id,
        provider=provider_name if provider_name in {"anthropic", "openai", "google", "codex"} else None,
    )
    try:
        out = await extract_bytes_with_schema(
            content=content,
            filename=filename,
            schema=schema,
            provider=provider,
            model_id=model_id,
            params=blob.get("params") or {"temperature": 0.0},
            global_notes=blob.get("global_notes") or "",
        )
    except Exception as exc:
        _log.warning(
            "v1 extract failure for published_id=%s user=%s key_prefix=%s hash_short=%s: %s",
            published_id,
            auth.user_id,
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


# ---------------------------------------------------------------------------
# M11 Phase B T10 — HTTP mirrors of `readiness_check` and `contract_diff` tools.
# Distinct from the prod fast-path `POST /v1/extract` above: those routes
# read project lab state (slug-scoped) rather than the frozen artifact, so
# CLI agents can drive the same publish-prep checks the in-session agent
# runs through its tool surface.
# ---------------------------------------------------------------------------


@router.get("/lab/projects/{slug}/readiness")
async def get_readiness(slug: str) -> dict:
    """Publish readiness checklist for the current lab state.

    Returns the same `{checks, soft_warnings, hard_pass, macro_f1,
    n_reviewed}` envelope the `readiness_check` tool produces. The route
    only validates inputs and routes 404s through the structured error
    shape; the business logic lives in `app.tools.publish.readiness_check`.
    """
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        return _error(404, "project_not_found", "no project at this slug")
    return await readiness_check_impl(settings.workspace_root, slug)


@router.get("/lab/projects/{slug}/contract-diff")
async def get_contract_diff(
    slug: str,
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
):
    """Diff two schema versions of this project.

    Query params (FastAPI doesn't let us name a python kwarg `from`):
    * `from` — base version_id (`v1`, `v2`, …). Omit to diff against the
      active version (or against an empty schema for first-publish previews).
    * `to` — target version_id. Omit to diff against the *current lab
      schema* (the in-progress edits that haven't been frozen yet).

    Echoes the `{added, removed, type_changed, enum_narrowed,
    is_breaking}` shape `app.tools.publish.contract_diff` produces. The
    extra `note` key surfaces when `from` resolves to "no prior version"
    so callers can tell first-publish previews from no-change diffs.
    """
    safe_slug(slug)
    settings = get_settings()
    ws = settings.workspace_root
    pj = project_json_path(ws, slug)
    if not pj.exists():
        return _error(404, "project_not_found", "no project at this slug")

    # Resolve `from` — explicit version, else project.active_version_id.
    project = json.loads(pj.read_text(encoding="utf-8"))
    from_id = from_ if from_ is not None else project.get("active_version_id")
    prev_schema: list[SchemaField] = []
    note: str | None = None
    if from_id:
        n = parse_version_id(from_id)
        if n is None:
            return _error(400, "invalid_version_id", f"invalid version_id: {from_id!r}")
        vp = version_path(ws, slug, n)
        if not vp.exists():
            return _error(404, "version_not_found", f"version {from_id} not found")
        prev_blob = json.loads(vp.read_text(encoding="utf-8"))
        prev_schema = [SchemaField(**f) for f in prev_blob.get("schema", [])]
    else:
        note = "no prior active version"

    # Resolve `to` — explicit version, else current lab schema.
    if to is not None:
        n = parse_version_id(to)
        if n is None:
            return _error(400, "invalid_version_id", f"invalid version_id: {to!r}")
        tp = version_path(ws, slug, n)
        if not tp.exists():
            return _error(404, "version_not_found", f"version {to} not found")
        to_blob = json.loads(tp.read_text(encoding="utf-8"))
        cand_schema = [SchemaField(**f) for f in to_blob.get("schema", [])]
    else:
        from app.tools.schema import read_schema
        cand_schema = await read_schema(ws, slug)

    out = contract_diff_impl(prev_schema, cand_schema)
    if note is not None:
        out["note"] = note
    return out


@router.get("/lab/keys/meta")
async def lab_keys_meta(user_id: str = "default") -> dict:
    """Workspace-level key metadata for `user_id` (defaults to the single-user
    placeholder `"default"`). One key per user-scope means a flat reveal —
    `hash_short / created_at / last_used` — no project scoping.
    """
    settings = get_settings()
    store = get_keystore(settings.workspace_root)
    store.reload_if_changed()
    row = next(
        (
            r for r in store._by_hash.values()
            if r.get("user_id") == user_id and r.get("scope") == "extract"
        ),
        None,
    )
    if row is None:
        return {
            "user_id": user_id,
            "key_hash_short": None,
            "created_at": None,
            "last_used": None,
        }
    return {
        "user_id": user_id,
        "key_hash_short": key_hash_short(row["hash"]),
        "created_at": row["created_at"],
        "last_used": row.get("last_used"),
    }
