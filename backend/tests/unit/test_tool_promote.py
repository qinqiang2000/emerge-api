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


async def test_promote_text_attachment_lands_as_doc(workspace: Path) -> None:
    """A text/JSON attachment (staged kind=note/schema/data) is promotable to
    docs/ exactly like a pdf — the extract pipeline accepts text files. This is
    the path a user takes to 校验 a dropped JSON: promote → extract_one."""
    slug = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    payload = b'{"a": 3, "b": 4, "c": 12}'
    await _stage_chat_attachment(workspace, slug, chat_id, "mul.json", payload)

    out = await promote_attachment_to_docs(workspace, slug, chat_id, "mul.json")
    assert out == {"final_name": "mul.json"}
    assert doc_path(workspace, slug, "mul.json").read_bytes() == payload
    meta = json.loads(doc_meta_path(workspace, slug, "mul.json").read_text())
    assert meta["ext"] == "json"
    assert meta["page_count"] == 1
    # Text docs have no raster geometry — page_sizes is empty (board falls back).
    assert meta["page_sizes"] == []


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


# ── promote_chat_to_project ──────────────────────────────────────────────


from app.chat.log import (
    append_event,
    ensure_chat_meta,
    unbound_chat_tombstone_path,
)
from app.chat.service import _UNBOUND_SLUG
from app.tools.promote import promote_chat_to_project
from app.workspace.paths import (
    chat_meta_path,
    chats_dir,
    unbound_chat_attachments_dir,
    unbound_chat_log_path,
    unbound_chat_meta_path,
    unbound_chats_root,
)


_UCID = "c_promotetest00"


async def _seed_unbound_chat(workspace: Path, chat_id: str = _UCID) -> None:
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, chat_id,
        first_user_message="hi there",
        has_attachments=False,
    )
    await append_event(
        workspace, _UNBOUND_SLUG, chat_id,
        {"type": "user", "text": "hi there"},
    )
    att_dir = unbound_chat_attachments_dir(workspace, chat_id)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "scan.pdf").write_bytes(b"%PDF-fake")


async def test_promote_chat_to_project_relocates_jsonl_meta_and_attachments(
    workspace: Path,
) -> None:
    await _seed_unbound_chat(workspace)

    out = await promote_chat_to_project(
        workspace, _UCID, name="美国发票",
    )
    new_slug = out["slug"]
    assert out["project_id"].startswith("p_")
    assert new_slug  # derive_slug normalises CJK + lowercase

    # Source paths under `_chats/` are gone — the rename moved them.
    assert not unbound_chat_log_path(workspace, _UCID).exists()
    assert not unbound_chat_meta_path(workspace, _UCID).exists()
    assert not (unbound_chats_root(workspace) / _UCID).exists()

    # Destination paths under the new project's `chats/` exist with the same
    # content.
    dst_log = chats_dir(workspace, new_slug) / f"{_UCID}.jsonl"
    assert dst_log.exists()
    first_line = json.loads(dst_log.read_text().splitlines()[0])
    assert first_line == {"type": "user", "text": "hi there"}

    dst_meta = chat_meta_path(workspace, new_slug, _UCID)
    assert dst_meta.exists()
    meta_data = json.loads(dst_meta.read_text())
    assert meta_data["label"] == "hi there"
    assert meta_data["kind"] == "chat"

    dst_att = chat_attachment_path(workspace, new_slug, _UCID, "scan.pdf")
    assert dst_att.exists()
    assert dst_att.read_bytes() == b"%PDF-fake"

    # The tombstone marker is in place so a still-streaming SDK turn at
    # `slug='_chats'` can't resurrect the unbound state.
    assert unbound_chat_tombstone_path(workspace, _UCID).exists()


async def test_promote_chat_partial_state_idempotent(workspace: Path) -> None:
    """If only the jsonl exists (no meta, no attachments), promote still
    runs — the missing pieces are skipped silently. Mirrors the half-deleted
    tolerance of `delete_project`."""
    # Bootstrap meta to pass the alive gate, then delete it so we exercise
    # the half-state branch in `relocate_unbound_chat`.
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="x",
        has_attachments=False,
    )
    await append_event(
        workspace, _UNBOUND_SLUG, _UCID, {"type": "user", "text": "x"},
    )
    unbound_chat_meta_path(workspace, _UCID).unlink()
    # No attachments dir at all.

    out = await promote_chat_to_project(workspace, _UCID, name="halfstate")
    new_slug = out["slug"]
    assert (chats_dir(workspace, new_slug) / f"{_UCID}.jsonl").exists()
    assert not chat_meta_path(workspace, new_slug, _UCID).exists()


async def test_promote_chat_creates_project_with_given_name(
    workspace: Path,
) -> None:
    out = await promote_chat_to_project(workspace, _UCID, name="empty-chat")
    assert out["slug"] == "empty-chat"
    assert (workspace / "empty-chat" / "project.json").exists()


async def test_promote_chat_blocks_further_unbound_writes(
    workspace: Path,
) -> None:
    """After promote, a stray `append_event(slug=_chats, chat_id)` must be
    silently dropped — never resurrect `_chats/<cid>.jsonl`."""
    await _seed_unbound_chat(workspace)
    await promote_chat_to_project(workspace, _UCID, name="post-promote")

    await append_event(
        workspace, _UNBOUND_SLUG, _UCID,
        {"type": "agent_text", "text": "trailing"},
    )
    assert not unbound_chat_log_path(workspace, _UCID).exists()
