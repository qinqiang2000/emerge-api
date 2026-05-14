from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_bytes, atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    doc_render_dir,
    docs_dir,
    docs_meta_dir,
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


def _dedupe_filename(docs_d: Path, name: str) -> str:
    """If `name` already exists under `docs/`, return `<stem> (1).<ext>` (or
    `(2)`, `(3)`, …) instead. Extension-aware split — the suffix after the
    final dot stays glued to the new copy."""
    target = docs_d / name
    if not target.exists():
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    i = 1
    while True:
        candidate = f"{stem} ({i})" + (f".{ext}" if ext else "")
        if not (docs_d / candidate).exists():
            return candidate
        i += 1


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
        final_name = _dedupe_filename(docs_d, slugged)
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


async def list_docs(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """List all docs in a project, newest-name-last. Reads each sidecar JSON.

    Files without sidecars are skipped silently — that state shouldn't happen
    under normal upload, but a half-written `docs/foo.pdf` (e.g. mid-fork)
    would otherwise crash the listing. Hidden entries (anything starting with
    `.` — that's our `.meta/` dir too) and subdirectories are skipped."""
    out: list[dict[str, Any]] = []
    d = docs_dir(workspace, project_id)
    if not d.exists():
        return out
    meta_d = docs_meta_dir(workspace, project_id)
    for child in sorted(d.iterdir()):
        if not child.is_file():
            continue
        if child.name.startswith("."):
            continue
        meta_p = meta_d / f"{child.name}.json"
        if not meta_p.exists():
            continue
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


async def pdf_render_page(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
    dpi: int = 150,
) -> Path:
    """Render a PDF page as PNG, cached at `docs/.meta/_render/{filename}/p{n}.png`.

    Re-renders only when the cache miss; the file path is keyed by the
    real filename so callers can hit this for the same doc across UI
    sessions without re-rendering."""
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
