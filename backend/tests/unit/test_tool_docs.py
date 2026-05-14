"""Tool-layer tests for `app.tools.docs` after the filename-native cutover.

For broader filename-storage coverage (dedup, render cache layout) see
`test_docs_storage.py`. This file pins the per-tool behaviors:
reject-on-unsupported-extension, magic-byte spoof rejection, and `read_doc`.
"""
from pathlib import Path

import pytest

from app.tools.docs import list_docs, read_doc, upload_doc
from app.tools.projects import create_project


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def test_upload_doc_writes_file_and_meta(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
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
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")
    items = await list_docs(workspace, pid)
    names = {it["filename"] for it in items}
    assert names == {"a.pdf", "b.pdf"}


async def test_read_doc_returns_bytes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    meta = await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    assert await read_doc(workspace, pid, meta["filename"]) == SAMPLE_PDF
