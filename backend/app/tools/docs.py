from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_bytes, atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    chat_attachments_dir,
    dedupe_filename,
    doc_meta_path,
    doc_path,
    doc_render_dir,
    docs_dir,
    docs_meta_dir,
    experiment_prediction_path,
    experiments_dir,
    prediction_draft_path,
    reviewed_path,
)


_ALLOWED_EXT = {"pdf": "pdf", "png": "png", "jpg": "jpg", "jpeg": "jpg"}

# Magic-byte signatures for the formats we accept. Sniffing the bytes lets us
# reject filename-spoofed uploads (e.g. HTML body with `.png` extension, or a
# clipboard paste that landed as `image.png` but is actually webp/heic). One
# bad image inlined into the agent session permanently 400s every subsequent
# turn — see chat service `_load_image_blocks` for the inline path — so we
# fail fast at the door.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)


# Filename slugging: filenames are now the on-disk handle, so we have to make
# them filesystem-safe. Strip path separators / NUL / control chars / leading
# dots; everything else (Unicode letters, spaces, parens, dashes, dots inside
# the name) is preserved. We are deliberately permissive — most users paste
# real document names like `2025VP00413 (Final).pdf` and we want those to
# survive intact.
_FS_REPLACE = re.compile(r'[\x00-\x1f\x7f/\\]+')


def _slug_filename(name: str) -> str:
    """Make `name` safe to use as a `docs/` directory entry. Replaces
    separators/control chars with `_`, strips leading dots/whitespace, and
    enforces a 255-byte ceiling (POSIX NAME_MAX). Empty result becomes
    `untitled.bin`."""
    cleaned = _FS_REPLACE.sub("_", name).strip().lstrip(".")
    if not cleaned:
        cleaned = "untitled.bin"
    # Enforce byte length cap. Preserve extension where possible.
    if len(cleaned.encode("utf-8")) > 255:
        stem, dot, ext = cleaned.rpartition(".")
        if dot:
            ext_b = ext.encode("utf-8")
            # leave ~10 bytes of headroom for the dot + ellipsis if needed
            budget = 255 - len(ext_b) - 1
            stem_b = stem.encode("utf-8")[:budget]
            cleaned = stem_b.decode("utf-8", errors="ignore") + "." + ext
        else:
            cleaned = cleaned.encode("utf-8")[:255].decode("utf-8", errors="ignore")
    return cleaned


def _ext_from_filename(filename: str) -> str:
    if "." not in filename:
        raise ValueError(f"unsupported file type: {filename!r}")
    raw = filename.rsplit(".", 1)[1].lower()
    if raw not in _ALLOWED_EXT:
        raise ValueError(f"unsupported file type: {filename!r}")
    return _ALLOWED_EXT[raw]


def _sniff_ext(data: bytes) -> str | None:
    """Return canonical extension implied by the leading magic bytes, or None
    if the payload doesn't match any of pdf / png / jpg."""
    for prefix, ext in _MAGIC:
        if data.startswith(prefix):
            return ext
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upload_doc(
    workspace: Path,
    project_id: str,
    data: bytes,
    filename: str,
) -> dict[str, Any]:
    """Persist `data` to `docs/<final_name>` and write a sidecar.

    `filename` is the user-provided original name. We slug it to make it
    filesystem-safe, then dedupe collisions ("a.pdf" → "a (1).pdf" if the
    first slot is taken). Returns the sidecar payload, including the final
    on-disk name under `filename`. There is no `doc_id`: filename IS the
    handle for every downstream lookup (predictions, reviewed, page render).
    """
    _ext_from_filename(filename)  # validates the extension before we touch disk
    # Magic-byte sniffing wins over the filename when they disagree (browser
    # clipboard often hands us `image.png` with non-PNG bytes underneath). For
    # legit uploads the two agree; for spoofed uploads sniffing rejects them.
    sniff = _sniff_ext(data)
    if sniff is None:
        raise ValueError(
            f"unsupported content: {filename!r} bytes don't match pdf/png/jpg"
        )
    ext = sniff
    page_count = _count_pages(data, ext)
    sha = hashlib.sha256(data).hexdigest()

    async with project_lock(workspace, project_id):
        docs_d = docs_dir(workspace, project_id)
        docs_d.mkdir(parents=True, exist_ok=True)
        docs_meta_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)

        slugged = _slug_filename(filename)
        final_name = dedupe_filename(docs_d, slugged)
        meta = {
            "filename": final_name,
            "original_name": filename,
            "ext": ext,
            "sha256": sha,
            "page_count": page_count,
            "uploaded_at": _now_iso(),
        }
        atomic_write_bytes(doc_path(workspace, project_id, final_name), data)
        atomic_write_json(doc_meta_path(workspace, project_id, final_name), meta)
    return meta


def _count_pages(data: bytes, ext: str) -> int:
    if ext != "pdf":
        return 1
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return 1


async def _repair_doc_sidecar(
    workspace: Path,
    project_id: str,
    filename: str,
) -> dict[str, Any] | None:
    """Rebuild a sidecar for a doc that lives in `docs/<filename>` without a
    matching `.meta/<filename>.json`. Sniffs the bytes for ext; returns the
    new sidecar payload, or None if the bytes don't match pdf/png/jpg (some
    non-doc file got dropped into `docs/` — leave alone, caller skips it).

    Caller must already hold `project_lock`. `rebuilt: True` flags the
    sidecar so audit can tell rebuilt from genuine upload."""
    try:
        data = doc_path(workspace, project_id, filename).read_bytes()
    except OSError:
        return None
    sniff = _sniff_ext(data)
    if sniff is None:
        return None
    meta = {
        "filename": filename,
        "original_name": filename,
        "ext": sniff,
        "sha256": hashlib.sha256(data).hexdigest(),
        "page_count": _count_pages(data, sniff),
        "uploaded_at": _now_iso(),
        "rebuilt": True,
    }
    atomic_write_json(doc_meta_path(workspace, project_id, filename), meta)
    return meta


async def list_docs(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """List all docs in a project, newest-name-last. Reads each sidecar JSON.

    Sidecar-missing files are rebuilt lazily — the agent can `Bash cp` files
    into a project's `docs/` and have them appear immediately, without going
    through `upload_doc`. Rebuild kicks in only when at least one orphan is
    seen, so the common all-sidecars-present path doesn't pay for the
    project lock. Hidden entries (anything starting with `.` — that's our
    `.meta/` dir too) and subdirectories are skipped."""
    out: list[dict[str, Any]] = []
    d = docs_dir(workspace, project_id)
    if not d.exists():
        return out
    meta_d = docs_meta_dir(workspace, project_id)

    entries: list[Path] = []
    for child in sorted(d.iterdir()):
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        entries.append(child)

    needs_repair = [c for c in entries if not (meta_d / f"{c.name}.json").exists()]
    if needs_repair:
        meta_d.mkdir(parents=True, exist_ok=True)
        async with project_lock(workspace, project_id):
            for child in needs_repair:
                meta_p = meta_d / f"{child.name}.json"
                if meta_p.exists():
                    continue  # raced with another caller — sidecar now exists
                await _repair_doc_sidecar(workspace, project_id, child.name)

    for child in entries:
        meta_p = meta_d / f"{child.name}.json"
        if not meta_p.exists():
            continue  # repair declined (bytes don't sniff to pdf/png/jpg)
        try:
            blob = json.loads(meta_p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        # Defensive: ensure the sidecar reports the actual on-disk name (older
        # forks may carry the source name). The real filename is `child.name`.
        blob["filename"] = child.name
        out.append(blob)
    return out


async def read_doc(workspace: Path, project_id: str, filename: str) -> bytes:
    """Return the raw bytes for one doc. `filename` is the on-disk name."""
    return doc_path(workspace, project_id, filename).read_bytes()


async def delete_doc(
    workspace: Path, project_id: str, filename: str,
) -> dict[str, Any]:
    """Remove a doc from the project. Wipes every artifact keyed off the
    filename — the file itself, sidecar meta, PDF render cache, draft
    prediction, reviewed JSON, and any per-experiment predictions — so the
    next `list_docs` no longer sees it and stale predictions can't resurrect
    later.

    No-op if the doc file isn't present (caller will see `removed: False`).
    Raises only on permission errors or filesystem failures the caller is
    expected to surface."""
    removed: list[str] = []

    async with project_lock(workspace, project_id):
        primary = doc_path(workspace, project_id, filename)
        if not primary.exists():
            return {"removed": False, "filename": filename, "artifacts": []}
        primary.unlink()
        removed.append("doc")

        side = doc_meta_path(workspace, project_id, filename)
        if side.exists():
            side.unlink()
            removed.append("meta")

        # NOTE: the render / textlayer / translate caches are deliberately
        # NOT wiped here. They moved to a workspace-level, content-addressed
        # store (`.cache/_render|_textlayer|_translate/{sha}/`) that may be
        # shared by the same bytes in other projects — and they're pure
        # functions of the doc, cheap to regenerate. Wiping on a per-project
        # delete would corrupt a sibling project's cache. Orphan entries are
        # harmless and can be GC'd workspace-wide later.
        draft = prediction_draft_path(workspace, project_id, filename)
        if draft.exists():
            draft.unlink()
            removed.append("prediction_draft")

        rev = reviewed_path(workspace, project_id, filename)
        if rev.exists():
            rev.unlink()
            removed.append("reviewed")

        edir = experiments_dir(workspace, project_id)
        if edir.exists():
            wiped = 0
            for sub in edir.iterdir():
                if not sub.is_dir():
                    continue
                ep = experiment_prediction_path(
                    workspace, project_id, sub.name, filename,
                )
                if ep.exists():
                    ep.unlink()
                    wiped += 1
            if wiped:
                removed.append(f"experiment_predictions×{wiped}")

    return {"removed": True, "filename": filename, "artifacts": removed}


async def pdf_render_page(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
    dpi: int = 150,
) -> Path:
    """Render a PDF page as PNG, cached at `.cache/_render/{sha}/p{n}.png`.

    Re-renders only on a cache miss; the path is content-addressed (keyed by
    the doc's sha256, not project/filename) so the same bytes across UI
    sessions — or copied into another project — hit one shared render."""
    import fitz  # PyMuPDF

    meta = json.loads(doc_meta_path(workspace, project_id, filename).read_text())
    if meta["ext"] != "pdf":
        raise ValueError(f"doc {filename!r} is not a pdf")
    src = doc_path(workspace, project_id, filename)

    cache_dir = doc_render_dir(workspace, project_id, filename)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"p{page}.png"
    if out.exists():
        return out

    with fitz.open(src) as pdf:
        if page < 1 or page > pdf.page_count:
            raise ValueError(f"page {page} out of range (1..{pdf.page_count})")
        pix = pdf[page - 1].get_pixmap(dpi=dpi)
        atomic_write_bytes(out, pix.tobytes("png"))
    return out


# Filename suffix → mime returned by `read_doc_image`. Mirrors
# `chat/service._load_image_blocks`'s `_IMAGE_MEDIA_TYPE` for the PNG/JPG
# branch; PDFs render to PNG via `pdf_render_page` first.
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}


# --- SDK-boundary image budget ----------------------------------------------
# Design trade-off (read before changing either number):
#
# * 1568px — Anthropic vision's optimal long edge. The API downsizes larger
#   images server-side before the model sees them, so pixels above this never
#   reach the agent's eyes anyway: resizing here costs ZERO vision quality.
# * 400KB — derived from the claude_agent_sdk control-protocol buffer
#   (1MB default) divided by the empirical number of images an agent pulls in
#   a single turn (2-3 pages, plus base64's ×1.37 inflation). A 150dpi A4 PNG
#   from `pdf_render_page` is 0.5-0.8MB raw; three of those blow the buffer
#   (`agent_failure: JSON exceeded maximum buffer size`) and kill the whole
#   turn. Fitted images land around 100-250KB, keeping multi-page pulls safe.
#
# These constants gate ONLY the SDK/agent boundary (`t_read_doc_image`
# wrapper, chat `_load_image_blocks`). Provider-direct paths (extract / audit
# judge / OCR / translate) call `read_doc_image` / `pdf_render_page` directly
# and must keep full resolution — hard rule.
_FIT_MAX_EDGE_PX = 1568
_FIT_MAX_BYTES = 400 * 1024
_FIT_JPEG_QUALITY = 80


def fit_image_for_agent(data: bytes, mime: str) -> tuple[bytes, str]:
    """Downscale + re-encode an image to the agent (SDK) budget.

    Pure function. Contract:
      - long edge > 1568px → proportional resize to 1568, JPEG q80.
      - dims already fine but bytes > 400KB → JPEG q80 re-encode at original
        size.
      - small AND light → returned unchanged (no decode round-trip cost paid
        beyond a header probe).
      - re-encode that comes out LARGER than the input → input wins.
      - any failure (corrupt bytes, unknown format) → input returned
        unchanged; can't-compress ≠ can't-see, downstream vision surfaces
        its own error.

    Alpha is flattened onto a white background (JPEG has no alpha channel);
    rendering the single-page image document with ``alpha=False`` does that
    natively in MuPDF.
    """
    try:
        import fitz  # PyMuPDF

        src = fitz.Pixmap(data)  # decode for pixel dims (also validates bytes)
        long_px = max(src.width, src.height)
        if long_px <= _FIT_MAX_EDGE_PX and len(data) <= _FIT_MAX_BYTES:
            return data, mime  # already within budget
        # Re-rasterize via a single-page image document. The page rect is in
        # points (i.e. scaled by the image's dpi metadata, usually 96), so
        # compute zoom in PIXEL terms: output px = rect_points × zoom.
        with fitz.open(stream=data) as img_doc:
            page = img_doc[0]
            target_px = min(long_px, _FIT_MAX_EDGE_PX)  # never upscale
            zoom = target_px / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        fitted = pix.tobytes("jpeg", jpg_quality=_FIT_JPEG_QUALITY)
        if len(fitted) >= len(data):
            return data, mime  # JPEG didn't help; keep the original
        return fitted, "image/jpeg"
    except Exception:
        return data, mime


async def read_doc_image(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int = 1,
) -> dict[str, Any]:
    """Return one doc as a base64 image payload for MCP tool-result content.

    - PNG/JPG → reads `docs/<filename>` directly; `page` is ignored
      (single-page assets).
    - PDF → calls `pdf_render_page(... page=page)` to (re-)materialize the
      cached PNG and reads those bytes; mime is `image/png`.

    `page_count` comes from the sidecar at `doc_meta_path(...)` (PNG/JPG
    sidecars carry `page_count=1` by `_count_pages` contract).

    Unsupported extensions raise `ValueError`. Missing files surface the
    underlying `OSError` from `read_bytes()` (same shape as `read_doc`).

    Returns:
        `{"data": "<base64>", "mime": "image/png"|"image/jpeg",
          "filename": <on-disk name>, "page": <int>, "page_count": <int>}`
    """
    if "." not in filename:
        raise ValueError(f"read_doc_image unsupported ext: {filename!r}")
    ext = filename.rsplit(".", 1)[1].lower()

    if ext in _IMAGE_MIME:
        data = doc_path(workspace, project_id, filename).read_bytes()
        mime = _IMAGE_MIME[ext]
        resolved_page = 1
    elif ext == "pdf":
        rendered = await pdf_render_page(
            workspace, project_id, filename, page=page,
        )
        data = rendered.read_bytes()
        mime = "image/png"
        resolved_page = page
    else:
        raise ValueError(f"read_doc_image unsupported ext: {filename!r}")

    try:
        meta = json.loads(
            doc_meta_path(workspace, project_id, filename).read_text()
        )
        page_count = int(meta.get("page_count", 1) or 1)
    except (OSError, json.JSONDecodeError):
        # Sidecar missing/corrupt isn't fatal — image bytes are valid; we
        # just don't know the page total. Falls back to 1 (best the agent
        # can do without it).
        page_count = 1

    b64 = base64.standard_b64encode(data).decode("ascii")
    return {
        "data": b64,
        "mime": mime,
        "filename": filename,
        "page": resolved_page,
        "page_count": page_count,
    }


class IngestLocalError(ValueError):
    """Caller-supplied path is outside the allowlist, missing, or otherwise
    unusable. The HTTP route surfaces this as 400; the MCP tool surfaces it as
    a normal tool error envelope."""


_INGEST_MAX_FILES_DEFAULT = 500


def _resolve_under_allowlist(path: Path, allowlist: tuple[Path, ...]) -> Path:
    """Return the resolved (symlink-followed) absolute path iff it lives under
    one of the allowlist roots. Resolution happens BEFORE the prefix check so
    `allowed_root/symlink_to_/etc` cannot escape.
    """
    try:
        resolved = path.expanduser().resolve()
    except (OSError, RuntimeError) as e:
        raise IngestLocalError(f"path not resolvable: {path}") from e
    for root in allowlist:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise IngestLocalError(
        f"path {str(resolved)!r} is outside the ingest allowlist; "
        f"set EMERGE_INGEST_LOCAL_EXTRA_ROOTS to whitelist it"
    )


async def ingest_local_path(
    workspace: Path,
    project_id: str,
    src_path: str,
    *,
    allowlist: tuple[Path, ...],
    recursive: bool = False,
    target: str = "docs",
    chat_id: str | None = None,
    max_files: int = _INGEST_MAX_FILES_DEFAULT,
) -> dict[str, Any]:
    """Bulk-ingest a local directory (or single file) into the project.

    Walks `src_path`, sniffs each candidate's leading bytes, and routes valid
    PDF / PNG / JPG payloads into either `docs/` (curated sample set, with
    sidecar + dedupe + sha) or `chats/<chat_id>/attachments/` (conversational
    scratch). Non-document files are silently skipped — same magic-byte
    contract as `upload_doc` / `stage_file`.

    `allowlist` is the resolved set of roots the caller is allowed to reach
    (see `Settings.ingest_allowlist`); the path must resolve under one of
    them or we raise `IngestLocalError`. `max_files` caps the per-call ingest
    so an accidental `/` never floods `docs/`.

    Returns:
        `{"target": "docs"|"attachments", "ingested": [{filename, original_name,
        ext, size}], "skipped": [{name, reason}], "errors": [{name, error}]}`
    """
    if target not in ("docs", "attachments"):
        raise IngestLocalError(f"target must be 'docs' or 'attachments', got {target!r}")
    if target == "attachments" and not chat_id:
        raise IngestLocalError("target='attachments' requires chat_id")

    resolved = _resolve_under_allowlist(Path(src_path), allowlist)
    if not resolved.exists():
        raise IngestLocalError(f"path does not exist: {resolved}")

    if resolved.is_file():
        candidates = [resolved]
    elif resolved.is_dir():
        candidates = sorted(
            p for p in (resolved.rglob("*") if recursive else resolved.iterdir())
            if p.is_file() and not p.name.startswith(".")
        )
    else:
        raise IngestLocalError(f"path is neither file nor directory: {resolved}")

    if len(candidates) > max_files:
        raise IngestLocalError(
            f"too many files at {resolved}: found {len(candidates)}, "
            f"max_files={max_files}"
        )

    ingested: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for fp in candidates:
        try:
            data = fp.read_bytes()
        except OSError as e:
            errors.append({"name": fp.name, "error": str(e)})
            continue
        sniff = _sniff_ext(data)
        if sniff is None:
            skipped.append({"name": fp.name, "reason": "not pdf/png/jpg"})
            continue
        # upload_doc validates by filename extension first; pass a normalized
        # filename so a `.heic` whose bytes are jpg still lands as `.jpg`.
        if "." in fp.name:
            stem = fp.name.rsplit(".", 1)[0]
        else:
            stem = fp.name
        landing_name = f"{stem}.{sniff}"
        try:
            if target == "docs":
                meta = await upload_doc(workspace, project_id, data, landing_name)
                ingested.append({
                    "filename": meta["filename"],
                    "original_name": fp.name,
                    "ext": meta["ext"],
                    "size": len(data),
                    "sha256": meta["sha256"],
                    "page_count": meta["page_count"],
                })
            else:
                assert chat_id is not None  # narrowed by the guard above
                target_dir = chat_attachments_dir(workspace, project_id, chat_id)
                target_dir.mkdir(parents=True, exist_ok=True)
                final_name = dedupe_filename(target_dir, landing_name)
                (target_dir / final_name).write_bytes(data)
                ingested.append({
                    "filename": final_name,
                    "original_name": fp.name,
                    "ext": sniff,
                    "size": len(data),
                })
        except ValueError as e:
            errors.append({"name": fp.name, "error": str(e)})
        except OSError as e:
            errors.append({"name": fp.name, "error": str(e)})

    return {
        "target": target,
        "ingested": ingested,
        "skipped": skipped,
        "errors": errors,
    }
