from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_bytes, atomic_write_json
from app.workspace.ids import new_doc_id
from app.workspace.lock import project_lock
from app.workspace.paths import doc_meta_path, doc_path, docs_dir


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
) -> str:
    name_ext = _ext_from_filename(filename)
    # Magic-byte sniffing wins over the filename when they disagree (browser
    # clipboard often hands us `image.png` with non-PNG bytes underneath). For
    # legit uploads the two agree; for spoofed uploads sniffing rejects them.
    sniff = _sniff_ext(data)
    if sniff is None:
        raise ValueError(
            f"unsupported content: {filename!r} bytes don't match pdf/png/jpg"
        )
    ext = sniff if sniff != name_ext else name_ext
    did = new_doc_id()
    sha = hashlib.sha256(data).hexdigest()
    page_count = _count_pages(data, ext)

    async with project_lock(workspace, project_id):
        docs_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(doc_path(workspace, project_id, did, ext), data)
        atomic_write_json(
            doc_meta_path(workspace, project_id, did),
            {
                "doc_id": did,
                "filename": filename,
                "ext": ext,
                "sha256": sha,
                "page_count": page_count,
                "uploaded_at": _now_iso(),
            },
        )
    return did


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
    out: list[dict[str, Any]] = []
    d = docs_dir(workspace, project_id)
    if not d.exists():
        return out
    for meta in sorted(d.glob("*.meta.json")):
        out.append(json.loads(meta.read_text()))
    return out


async def read_doc(workspace: Path, project_id: str, doc_id: str) -> bytes:
    meta_p = doc_meta_path(workspace, project_id, doc_id)
    meta = json.loads(meta_p.read_text())
    return doc_path(workspace, project_id, doc_id, meta["ext"]).read_bytes()


async def pdf_render_page(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    page: int,
    dpi: int = 150,
) -> Path:
    """Render PDF page as PNG cached under docs/_render/{doc_id}_p{n}.png."""
    import fitz  # PyMuPDF

    meta = json.loads(doc_meta_path(workspace, project_id, doc_id).read_text())
    if meta["ext"] != "pdf":
        raise ValueError(f"doc {doc_id} is not a pdf")
    src = doc_path(workspace, project_id, doc_id, meta["ext"])

    cache_dir = docs_dir(workspace, project_id) / "_render"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{doc_id}_p{page}.png"
    if out.exists():
        return out

    with fitz.open(src) as pdf:
        if page < 1 or page > pdf.page_count:
            raise ValueError(f"page {page} out of range (1..{pdf.page_count})")
        pix = pdf[page - 1].get_pixmap(dpi=dpi)
        atomic_write_bytes(out, pix.tobytes("png"))
    return out
