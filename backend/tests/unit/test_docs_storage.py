"""Filename-native storage smoke tests (post-d_xxx removal).

These tests pin the contract that emerged in the at-mention refactor:
- `upload_doc` returns `{filename, ext, page_count, sha256, uploaded_at, original_name}`
- on-disk layout is `docs/<filename>` plus a sidecar at `docs/.meta/<filename>.json`
- collisions on the original name get `(1)`, `(2)`, … appended (extension-aware)
- `list_docs` glob skips `.meta/` and never resurrects a `doc_id`
- `pdf_render_page` caches under `docs/.meta/_render/<filename>/p{n}.png`
"""
from pathlib import Path

import pytest

from app.tools.docs import list_docs, pdf_render_page, upload_doc
from app.tools.projects import create_project


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def test_upload_returns_filename_and_meta(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    meta = await upload_doc(workspace, pid, SAMPLE_PDF, "invoice-001.pdf")
    # New shape: no doc_id key.
    assert "doc_id" not in meta
    assert meta["filename"] == "invoice-001.pdf"
    assert meta["ext"] == "pdf"
    assert meta["sha256"]
    assert meta["uploaded_at"]
    assert meta["original_name"] == "invoice-001.pdf"
    # On-disk: file is at docs/<name>, sidecar at docs/.meta/<name>.json.
    assert (workspace / pid / "docs" / "invoice-001.pdf").read_bytes() == SAMPLE_PDF
    assert (workspace / pid / "docs" / ".meta" / "invoice-001.pdf.json").exists()


async def test_upload_same_name_twice_yields_dedup_suffix(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    a = await upload_doc(workspace, pid, SAMPLE_PDF, "report.pdf")
    b = await upload_doc(workspace, pid, SAMPLE_PDF, "report.pdf")
    c = await upload_doc(workspace, pid, SAMPLE_PDF, "report.pdf")
    assert a["filename"] == "report.pdf"
    assert b["filename"] == "report (1).pdf"
    assert c["filename"] == "report (2).pdf"
    docs_d = workspace / pid / "docs"
    assert (docs_d / "report.pdf").exists()
    assert (docs_d / "report (1).pdf").exists()
    assert (docs_d / "report (2).pdf").exists()
    # Each gets its own sidecar.
    meta_d = docs_d / ".meta"
    assert (meta_d / "report.pdf.json").exists()
    assert (meta_d / "report (1).pdf.json").exists()
    assert (meta_d / "report (2).pdf.json").exists()


async def test_list_docs_returns_filenames_not_doc_ids(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await upload_doc(workspace, pid, SAMPLE_PDF, "a.pdf")
    await upload_doc(workspace, pid, SAMPLE_PDF, "b.pdf")
    items = await list_docs(workspace, pid)
    names = {it["filename"] for it in items}
    assert names == {"a.pdf", "b.pdf"}
    # Defensive: nothing in the list shape leaks the legacy doc_id key.
    for it in items:
        assert "doc_id" not in it
    # `.meta/` directory is skipped by the listing.
    assert not any(it.get("filename", "").startswith(".") for it in items)


async def test_list_docs_skips_dotfiles_and_sidecar_dir(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await upload_doc(workspace, pid, SAMPLE_PDF, "real.pdf")
    # Drop a stray file mimicking what a stale runtime could leave behind.
    (workspace / pid / "docs" / ".DS_Store").write_bytes(b"junk")
    items = await list_docs(workspace, pid)
    assert {it["filename"] for it in items} == {"real.pdf"}


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


async def test_pdf_render_page_caches_under_meta_render(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    meta = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    out = await pdf_render_page(workspace, pid, meta["filename"], page=1)
    assert out.exists()
    assert out.suffix == ".png"
    # Cache lives under docs/.meta/_render/<filename>/p1.png — not the old
    # `_render/{doc_id}_p1.png` flat scheme.
    assert out.parent == workspace / pid / "docs" / ".meta" / "_render" / "sample.pdf"
    assert out.name == "p1.png"
    # Magic-byte sanity check.
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_pdf_render_page_invalid_page_raises(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    meta = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "sample.pdf")
    with pytest.raises(ValueError, match="page"):
        await pdf_render_page(workspace, pid, meta["filename"], page=99)
