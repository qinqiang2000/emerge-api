"""Tool-layer tests for `app.tools.docs` after the filename-native cutover.

For broader filename-storage coverage (dedup, render cache layout) see
`test_docs_storage.py`. This file pins the per-tool behaviors:
reject-on-unsupported-extension, magic-byte spoof rejection, `read_doc`, and
the pull-mode `read_doc_image` vision tool (progressive doc vision).
"""
import base64
import json
from pathlib import Path

import pytest

from app.tools.docs import list_docs, read_doc, read_doc_image, upload_doc
from app.tools.projects import create_project
from app.workspace.paths import doc_meta_path, doc_path, docs_dir, docs_meta_dir


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"
SAMPLE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SAMPLE_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32

_PDF_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_upload_doc_writes_file_and_meta(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, SAMPLE_PDF, "invoice-001.pdf")
    pdir = workspace / pid / "docs"
    assert (pdir / "invoice-001.pdf").read_bytes() == SAMPLE_PDF
    sidecar = pdir / ".meta" / "invoice-001.pdf.json"
    import json
    blob = json.loads(sidecar.read_text())
    assert blob["filename"] == "invoice-001.pdf"
    assert blob["original_name"] == "invoice-001.pdf"
    assert blob["sha256"]
    assert blob["uploaded_at"]
    assert meta["filename"] == "invoice-001.pdf"


async def test_upload_doc_rejects_non_pdf(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(ValueError, match="unsupported"):
        await upload_doc(workspace, pid, b"...", "weird.docx")


async def test_upload_doc_rejects_spoofed_extension(workspace: Path) -> None:
    """A `.png` filename whose bytes are actually HTML must be rejected.

    Without this guard the bad bytes get inlined as an image content block in
    the agent's session transcript, which permanently 400s every subsequent
    turn in that chat — see chat service `_load_image_blocks`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(ValueError, match="unsupported content"):
        await upload_doc(workspace, pid, b"<!doctype html><html>...", "image.png")


async def test_list_docs_returns_uploaded(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")
    items = await list_docs(workspace, pid)
    names = {it["filename"] for it in items}
    assert names == {"a.pdf", "b.pdf"}


async def test_read_doc_returns_bytes(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    assert await read_doc(workspace, pid, meta["filename"]) == SAMPLE_PDF


# `read_doc_image` — progressive doc vision (2026-05-16 plan).
#
# These tests pin the pull-mode tool that lets the agent fetch a doc's pixels
# on demand instead of having the user re-paste. The function must agree with
# `_load_image_blocks`'s base64 encoding (`base64.standard_b64encode`) so
# anything the agent sees via this path is byte-identical to push-mode.


async def test_read_doc_image_png_round_trip(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, SAMPLE_PNG, "scan.png")
    out = await read_doc_image(workspace, pid, meta["filename"])
    # Bytes must round-trip — agent + push path share encoder, so the agent
    # sees exactly the on-disk bytes.
    assert out["data"] == base64.b64encode(SAMPLE_PNG).decode()
    assert out["mime"] == "image/png"
    assert out["filename"] == "scan.png"
    assert out["page"] == 1
    assert out["page_count"] == 1


async def test_read_doc_image_jpg_round_trip(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, SAMPLE_JPG, "scan.jpg")
    out = await read_doc_image(workspace, pid, meta["filename"])
    assert out["data"] == base64.b64encode(SAMPLE_JPG).decode()
    assert out["mime"] == "image/jpeg"
    assert out["filename"] == "scan.jpg"
    assert out["page"] == 1
    assert out["page_count"] == 1


async def test_read_doc_image_jpeg_extension_mime(workspace: Path) -> None:
    """`.jpeg` filename → mime `image/jpeg` (extension table covers both
    `.jpg` and `.jpeg`, mirroring `chat/service._IMAGE_MEDIA_TYPE`)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    # upload_doc slugs `.jpeg` → on-disk filename keeps `.jpeg` ext.
    meta = await upload_doc(workspace, pid, SAMPLE_JPG, "scan.jpeg")
    out = await read_doc_image(workspace, pid, meta["filename"])
    assert out["mime"] == "image/jpeg"


async def test_read_doc_image_pdf_uses_render_cache(workspace: Path) -> None:
    """PDF → renders via `pdf_render_page` and reads the cached PNG. The
    cached file must exist on disk after the call (same location as the
    `pdf_render_page` contract)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, _PDF_FIXTURE.read_bytes(), "invoice.pdf")
    out = await read_doc_image(workspace, pid, meta["filename"], page=1)
    sha = meta["sha256"]
    cached = workspace / ".cache" / "_render" / sha / "p1.png"
    assert cached.exists(), "pdf_render_page should have written the cache"
    # The bytes we returned are exactly the cached PNG (base64-decoded).
    assert base64.b64decode(out["data"]) == cached.read_bytes()
    assert out["mime"] == "image/png"
    assert out["page"] == 1
    assert out["page_count"] >= 1


async def test_read_doc_image_pdf_page_out_of_range(workspace: Path) -> None:
    """Out-of-range page should surface the same ValueError shape as
    `pdf_render_page` ('page N out of range (1..M)')."""
    pid = (await create_project(workspace, name="x"))["slug"]
    meta = await upload_doc(workspace, pid, _PDF_FIXTURE.read_bytes(), "invoice.pdf")
    with pytest.raises(ValueError, match="page"):
        await read_doc_image(workspace, pid, meta["filename"], page=99)


async def test_read_doc_image_unsupported_extension(workspace: Path) -> None:
    """A `.heic` doc that somehow made it onto disk (bypassing upload_doc's
    extension allowlist) must be rejected by the tool. We synthesize one
    directly so the test exercises the tool's own guard, not upload_doc's."""
    pid = (await create_project(workspace, name="x"))["slug"]
    # Manually plant a .heic in docs/ + a sidecar so the listing isn't
    # required for this code path; we just need the file present.
    docs_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    doc_path(workspace, pid, "phone.heic").write_bytes(b"ftypheic" + b"\x00" * 16)
    doc_meta_path(workspace, pid, "phone.heic").write_text(
        json.dumps({"filename": "phone.heic", "ext": "heic", "page_count": 1})
    )
    with pytest.raises(ValueError, match="unsupported ext"):
        await read_doc_image(workspace, pid, "phone.heic")


async def test_read_doc_image_no_extension_rejected(workspace: Path) -> None:
    """A filename without any extension is unsupported (same family of
    rejection as `.heic`)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(ValueError, match="unsupported ext"):
        await read_doc_image(workspace, pid, "no_extension_at_all")


async def test_read_doc_image_missing_file_raises_oserror(workspace: Path) -> None:
    """Missing on-disk file → bubble the OSError from `read_bytes()`. Same
    behaviour as `read_doc`. Agent will see this as a tool error."""
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(OSError):
        await read_doc_image(workspace, pid, "does-not-exist.png")
