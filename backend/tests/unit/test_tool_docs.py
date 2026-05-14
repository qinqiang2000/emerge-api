import json
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.tools.docs import upload_doc, list_docs, read_doc, pdf_render_page


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def test_upload_doc_writes_file_and_meta(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, SAMPLE_PDF, "invoice-001.pdf")
    pdir = workspace / pid / "docs"
    assert (pdir / f"{did}.pdf").read_bytes() == SAMPLE_PDF
    meta = json.loads((pdir / f"{did}.meta.json").read_text())
    assert meta["filename"] == "invoice-001.pdf"
    assert meta["sha256"]
    assert meta["uploaded_at"]


async def test_upload_doc_rejects_non_pdf(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    with pytest.raises(ValueError, match="unsupported"):
        await upload_doc(workspace, pid, b"...", "weird.docx")


async def test_upload_doc_rejects_spoofed_extension(workspace: Path) -> None:
    """A `.png` filename whose bytes are actually HTML must be rejected.

    Without this guard the bad bytes get inlined as an image content block in
    the agent's session transcript, which permanently 400s every subsequent
    turn in that chat — see chat service `_load_image_blocks`."""
    pid = await create_project(workspace, name="x")
    with pytest.raises(ValueError, match="unsupported content"):
        await upload_doc(workspace, pid, b"<!doctype html><html>...", "image.png")


async def test_list_docs_returns_uploaded(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    d1 = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    d2 = await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")
    items = await list_docs(workspace, pid)
    ids = {it["doc_id"] for it in items}
    assert ids == {d1, d2}


async def test_read_doc_returns_bytes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    assert await read_doc(workspace, pid, did) == SAMPLE_PDF


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_pdf_render_page_writes_png(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    png_path = await pdf_render_page(workspace, pid, did, page=1)
    assert png_path.exists()
    assert png_path.suffix == ".png"
    # Quick magic-byte check
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_pdf_render_page_invalid_page_raises(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    with pytest.raises(ValueError, match="page"):
        await pdf_render_page(workspace, pid, did, page=99)
