from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from app.auth.deps import bind_workspace, current_ws
from fastapi.responses import FileResponse

from app.api.routes._safety import safe_chat_id, safe_filename, safe_slug
from app.config import get_settings
from app.tools.docs import IngestLocalError, ingest_local_path, upload_doc
from app.tools.promote import promote_attachment_to_docs as promote_attachment_impl
from app.workspace.paths import (
    chat_attachment_path,
    chat_attachments_dir,
    dedupe_filename,
)
from app.workspace.staging import (
    StagingError,
    _classify_kind,
    _raw_ext,
    _validate_text_payload,
    _DOC_EXT,
    stage_file,
)


router = APIRouter(dependencies=[Depends(bind_workspace)])


_ATTACHMENT_MEDIA = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    # Text-shaped attachments are served as plain text so a browser can preview
    # them inline. Frontend chips only navigate to these for non-doc kinds.
    "yml": "text/yaml; charset=utf-8",
    "yaml": "text/yaml; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


@router.post("/lab/projects/{slug}/upload")
async def upload(slug: str, file: UploadFile = File(...)) -> dict:
    """Upload a doc to `docs/<final_name>`. Response carries the post-dedup
    filename — there is no `doc_id` anymore. The frontend uses this filename
    as the doc handle for every subsequent call (pages, reviewed,
    predictions)."""
    safe_slug(slug)
    settings = get_settings()
    data = await file.read()
    try:
        meta = await upload_doc(current_ws(), slug, data, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "filename": meta["filename"],
        "ext": meta["ext"],
        "page_count": meta["page_count"],
        "sha256": meta["sha256"],
        "uploaded_at": meta["uploaded_at"],
        "original_name": meta["original_name"],
    }


@router.post("/lab/uploads/staging")
async def upload_staging(file: UploadFile = File(...)) -> dict[str, Any]:
    """Stage a single file under `workspace/_staging/{stage_token}/`.

    No project is created — the caller will pass the returned `stage_token`
    into the next chat turn's `attachments[i].stage_token`, where the backend
    mints the project and claims the staged file. Cleanup of unclaimed
    staging dirs happens on app startup (see `cleanup_stale`).
    """
    settings = get_settings()
    data = await file.read()
    try:
        info = await stage_file(current_ws(), data, file.filename or "")
    except StagingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return info


_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


def _sniff_doc_ext(data: bytes) -> str | None:
    """Magic-byte sniff for binary doc payloads (pdf/png/jpg). Text-shaped
    payloads (yml/json/csv/txt/md) have no stable magic and go through
    `_validate_text_payload` instead."""
    for prefix, ext in _MAGIC:
        if data.startswith(prefix):
            return ext
    return None


@router.post("/lab/projects/{slug}/chats/{chat_id}/attach")
async def attach_to_chat(
    slug: str, chat_id: str, file: UploadFile = File(...),
) -> dict[str, Any]:
    """Write a pasted/dropped file to `chats/<chat_id>/attachments/` with
    dedupe. NOT into `docs/` — the file is conversational scratch; only an
    explicit user-confirmed `promote_attachment_to_docs` call moves it into
    the curated sample set.

    Mirrors the staging-time gate: pdf/png/jpg go through the magic-byte
    allowlist; yml/yaml/json/csv/txt/md go through the UTF-8 + size cap.
    Returns `{filename, kind}` so the frontend chip can route by kind
    (e.g. doc → preview, schema → "import?" prompt)."""
    safe_slug(slug)
    safe_chat_id(chat_id)
    src_name = file.filename or ""
    safe_filename(src_name)
    data = await file.read()
    try:
        raw = _raw_ext(src_name)
    except StagingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if raw in _DOC_EXT:
        sniff = _sniff_doc_ext(data)
        if sniff is None:
            raise HTTPException(
                status_code=400,
                detail="unsupported content: bytes don't match pdf/png/jpg",
            )
    else:
        try:
            _validate_text_payload(src_name, data)
        except StagingError as e:
            raise HTTPException(status_code=400, detail=str(e))
    settings = get_settings()
    target_dir = chat_attachments_dir(current_ws(), slug, chat_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    final_name = dedupe_filename(target_dir, src_name)
    (target_dir / final_name).write_bytes(data)
    kind = _classify_kind(final_name, data)
    return {"filename": final_name, "kind": kind}


@router.post("/lab/projects/{slug}/ingest-local")
async def ingest_local(slug: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Bulk-ingest a server-local path (file or directory) into the project.

    The path must resolve under one of the configured ingest roots
    (`Settings.ingest_allowlist`). Non-pdf/png/jpg payloads are silently
    skipped via magic-byte sniffing — same filter as `upload_doc`. Caller
    chooses `target='docs'` (curated sample set) or `target='attachments'`
    (chat-scoped scratch; requires `chat_id`).

    Body schema:
        {"path": str, "recursive"?: bool, "target"?: "docs"|"attachments",
         "chat_id"?: str}
    """
    safe_slug(slug)
    path = body.get("path")
    if not isinstance(path, str) or not path:
        raise HTTPException(status_code=400, detail="path is required")
    recursive = bool(body.get("recursive", False))
    target = str(body.get("target", "docs"))
    chat_id = body.get("chat_id")
    if chat_id is not None:
        safe_chat_id(str(chat_id))
    settings = get_settings()
    try:
        result = await ingest_local_path(
            current_ws(),
            slug,
            path,
            allowlist=settings.ingest_allowlist(),
            recursive=recursive,
            target=target,
            chat_id=chat_id or None,
        )
    except IngestLocalError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/lab/projects/{slug}/chats/{chat_id}/attachments/{filename:path}")
async def get_chat_attachment(
    slug: str, chat_id: str, filename: str,
) -> FileResponse:
    """Serve a chat attachment for inline rendering (image thumbnails, PDF
    download chips). Validates slug + chat_id + filename to keep callers
    inside the conversation's attachment dir."""
    safe_slug(slug)
    safe_chat_id(chat_id)
    safe_filename(filename)
    settings = get_settings()
    path = chat_attachment_path(current_ws(), slug, chat_id, filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="attachment_not_found")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    media = _ATTACHMENT_MEDIA.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media)


# ---------------------------------------------------------------------------
# M11 Phase B T11 — HTTP mirror of the `promote_attachment_to_docs` tool.
# A chat attachment becomes a curated `docs/` sample only via this explicit,
# user-acked promotion path. The route closes the AI-native API symmetry gap
# (memory `feedback_ai_native_api_symmetry`) so a CLI agent driving HTTP can
# promote without going through chat. Idempotent on re-promote of an already-
# moved file: the chat source is gone, so we surface the existing docs name.
# ---------------------------------------------------------------------------


@router.post("/lab/projects/{slug}/chats/{chat_id}/attachments/{filename:path}/promote")
async def post_promote_attachment(
    slug: str, chat_id: str, filename: str,
) -> dict[str, str]:
    """Promote a chat-scoped attachment into `docs/`. Returns
    `{target_filename}` — the post-dedupe on-disk handle (may differ from
    the chat filename if `docs/` already had a same-named file).

    Idempotency: re-promoting a file that's already been promoted (chat
    source is gone but `docs/<filename>` exists) returns the same target
    name without re-uploading. 404 only when neither the chat source nor
    the docs target exists."""
    safe_slug(slug)
    safe_chat_id(chat_id)
    safe_filename(filename)
    settings = get_settings()
    try:
        out = await promote_attachment_impl(
            current_ws(), slug, chat_id, filename,
        )
    except FileNotFoundError:
        # Idempotent fallback: if the chat source is gone but the file is
        # already in docs/ under the original name, treat the re-promote
        # as a no-op and echo the target. This matches the tool's
        # documented contract ("re-promote = no-op, returns same target").
        from app.workspace.paths import doc_path
        existing = doc_path(current_ws(), slug, filename)
        if existing.exists() and existing.is_file():
            return {"target_filename": filename}
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "attachment_not_found",
                "error_message_en": (
                    f"chat attachment not found: {slug}/{chat_id}/{filename}"
                ),
            },
        )
    return {"target_filename": out["final_name"]}
