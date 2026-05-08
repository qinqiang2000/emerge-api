import json
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.tools.docs import upload_doc, list_docs, read_doc


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
