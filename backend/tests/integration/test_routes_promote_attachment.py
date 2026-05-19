"""HTTP coverage for the M11 Phase B T11 lab route on upload.py:

* `POST /lab/projects/{slug}/chats/{chat_id}/attachments/{filename}/promote`

A chat attachment becomes a curated `docs/` sample only via this explicit,
user-acked promotion path. The route mirrors the `promote_attachment_to_docs`
tool — same sidecar / sha256 / dedupe semantics as `upload_doc`.

Idempotency contract: re-promoting a file that's already been promoted (the
chat-side source is gone but `docs/<filename>` exists) returns the same
`target_filename` without re-uploading. 404 only when neither source nor
docs target exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.workspace.paths import (
    chat_attachment_path,
    chat_attachments_dir,
    doc_meta_path,
    doc_path,
)


SAMPLE_PDF = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 1\n0000000000 65535 f\n%%EOF\n"
)


async def _stage_chat_attachment(
    workspace: Path, slug: str, chat_id: str, filename: str, data: bytes,
) -> None:
    att_dir = chat_attachments_dir(workspace, slug, chat_id)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / filename).write_bytes(data)


@pytest.mark.asyncio
async def test_promote_route_moves_chat_attachment_to_docs(workspace: Path) -> None:
    """Happy path: chat-scoped file → `docs/<final_name>` + sidecar; the
    chat-side source is removed (no duplicates lingering)."""
    slug = (await create_project(workspace, name="promote-test"))["slug"]
    chat_id = "c_abc123def456"
    await _stage_chat_attachment(workspace, slug, chat_id, "scan.pdf", SAMPLE_PDF)

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/chats/{chat_id}/attachments/scan.pdf/promote",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"target_filename": "scan.pdf"}

    # File at docs/<final_name>, sidecar at docs/.meta/<final_name>.json.
    assert doc_path(workspace, slug, "scan.pdf").read_bytes() == SAMPLE_PDF
    meta = json.loads(doc_meta_path(workspace, slug, "scan.pdf").read_text())
    assert meta["filename"] == "scan.pdf"
    assert "sha256" in meta and "page_count" in meta

    # Chat source removed.
    assert not chat_attachment_path(workspace, slug, chat_id, "scan.pdf").exists()


@pytest.mark.asyncio
async def test_promote_route_idempotent_when_already_in_docs(workspace: Path) -> None:
    """Re-promoting a file whose chat source has already been moved into
    `docs/` returns the same target name (no error, no duplicate)."""
    slug = (await create_project(workspace, name="idem-test"))["slug"]
    chat_id = "c_abc123def456"
    await _stage_chat_attachment(workspace, slug, chat_id, "bill.pdf", SAMPLE_PDF)

    client = TestClient(app)
    # First promote — moves the file into docs/.
    r1 = client.post(
        f"/lab/projects/{slug}/chats/{chat_id}/attachments/bill.pdf/promote",
    )
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"target_filename": "bill.pdf"}
    assert doc_path(workspace, slug, "bill.pdf").exists()
    assert not chat_attachment_path(workspace, slug, chat_id, "bill.pdf").exists()

    # Second promote — chat source is gone, but docs target exists.
    # Idempotent contract: same target_filename returned, no 404, no
    # duplicate dedupe (would have made `bill (1).pdf` if re-uploaded).
    r2 = client.post(
        f"/lab/projects/{slug}/chats/{chat_id}/attachments/bill.pdf/promote",
    )
    assert r2.status_code == 200, r2.text
    assert r2.json() == {"target_filename": "bill.pdf"}
    # No accidental dedupe — `bill (1).pdf` must NOT exist.
    assert not doc_path(workspace, slug, "bill (1).pdf").exists()


@pytest.mark.asyncio
async def test_promote_route_404_when_neither_source_nor_target(
    workspace: Path,
) -> None:
    """No chat attachment AND no docs target → structured 404 envelope."""
    slug = (await create_project(workspace, name="ghost-test"))["slug"]
    chat_id = "c_abc123def456"

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/chats/{chat_id}/attachments/ghost.pdf/promote",
    )
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert detail["error_code"] == "attachment_not_found"


@pytest.mark.asyncio
async def test_promote_route_dedupe_on_name_collision(workspace: Path) -> None:
    """Promote into a `docs/` that already has a same-name file (from an
    earlier upload, not a re-promote) → dedupe kicks in and the target
    filename gains the `(1)` suffix. Mirrors `upload_doc`'s contract."""
    from app.tools.docs import upload_doc

    slug = (await create_project(workspace, name="collide-test"))["slug"]
    chat_id = "c_abc123def456"
    # Pre-seed docs with a different file under the same name (different
    # bytes → different sha → dedupe rather than no-op).
    await upload_doc(workspace, slug, b"%PDF-1.4 different bytes", "scan.pdf")
    assert doc_path(workspace, slug, "scan.pdf").exists()

    # Now stage a chat attachment with the SAME name but different bytes
    # so the promotion has to dedupe.
    await _stage_chat_attachment(workspace, slug, chat_id, "scan.pdf", SAMPLE_PDF)

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/chats/{chat_id}/attachments/scan.pdf/promote",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Dedupe puts the promoted bytes under `scan (1).pdf`.
    assert body["target_filename"] == "scan (1).pdf"
    assert doc_path(workspace, slug, "scan (1).pdf").read_bytes() == SAMPLE_PDF
    # Chat source removed.
    assert not chat_attachment_path(workspace, slug, chat_id, "scan.pdf").exists()


@pytest.mark.asyncio
async def test_promote_route_rejects_invalid_chat_id(workspace: Path) -> None:
    """Slug-shaped chat_id that doesn't match `c_xxxxxxxxxxxx` → 400 via
    `safe_chat_id`. Belt-and-braces against malformed CLI calls."""
    slug = (await create_project(workspace, name="bad-cid"))["slug"]
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/chats/not-a-chat-id/attachments/x.pdf/promote",
    )
    assert r.status_code == 400, r.text
