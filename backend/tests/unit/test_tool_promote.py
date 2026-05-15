"""Tests for `promote_attachment_to_docs`.

A chat attachment becomes a curated sample only via this tool. The promotion
must route through `upload_doc` so the sidecar / sha256 / dedupe semantics
stay identical to a normal `/lab/projects/{slug}/upload`. The source chat
file must be removed once promoted (no duplicates lingering).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.promote import promote_attachment_to_docs
from app.workspace.paths import (
    chat_attachment_path,
    chat_attachments_dir,
    doc_meta_path,
    doc_path,
)


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"


async def _stage_chat_attachment(
    workspace: Path, slug: str, chat_id: str, filename: str, data: bytes,
) -> None:
    att_dir = chat_attachments_dir(workspace, slug, chat_id)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / filename).write_bytes(data)


async def test_promote_attachment_to_docs_moves_with_sidecar_and_dedupe(
    workspace: Path,
) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    await _stage_chat_attachment(workspace, slug, chat_id, "scan.pdf", SAMPLE_PDF)

    out = await promote_attachment_to_docs(workspace, slug, chat_id, "scan.pdf")
    assert out == {"final_name": "scan.pdf"}
    # File at docs/<final_name>, sidecar at docs/.meta/<final_name>.json.
    assert doc_path(workspace, slug, "scan.pdf").read_bytes() == SAMPLE_PDF
    meta = json.loads(doc_meta_path(workspace, slug, "scan.pdf").read_text())
    assert meta["filename"] == "scan.pdf"
    assert "sha256" in meta and "page_count" in meta
    # Second promote of same name collides → dedupe.
    await _stage_chat_attachment(workspace, slug, chat_id, "scan.pdf", SAMPLE_PDF)
    out2 = await promote_attachment_to_docs(workspace, slug, chat_id, "scan.pdf")
    assert out2 == {"final_name": "scan (1).pdf"}


async def test_promote_removes_chat_source_file(workspace: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    await _stage_chat_attachment(workspace, slug, chat_id, "bill.pdf", SAMPLE_PDF)
    src = chat_attachment_path(workspace, slug, chat_id, "bill.pdf")
    assert src.exists()
    await promote_attachment_to_docs(workspace, slug, chat_id, "bill.pdf")
    assert not src.exists(), "chat-scoped source must be removed on promote"


async def test_promote_missing_file_raises(workspace: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    with pytest.raises(FileNotFoundError):
        await promote_attachment_to_docs(workspace, slug, chat_id, "ghost.pdf")
