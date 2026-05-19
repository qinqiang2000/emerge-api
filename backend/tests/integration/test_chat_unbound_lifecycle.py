"""End-to-end backend lifecycle for an unbound chat.

  1. Create (no minting, just a chat_id).
  2. Send a turn dispatched at `slug='_chats'` — events land under
     `_chats/<cid>.jsonl`, attachments under `_chats/<cid>/attachments/`,
     no project minted.
  3. Promote via `promote_chat_to_project` — jsonl + meta + attachments
     atomically relocate under the new project's `chats/`.
  4. The `_chats/` slot is empty (tombstone in place) post-promote;
     `list_projects` surfaces the new project.

This is the Phase-1 backend contract Phase-2 frontend will consume.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from app.chat.log import (
    append_event,
    ensure_chat_meta,
    list_unbound_chats,
    unbound_chat_tombstone_path,
)
from app.chat.service import ChatService, _UNBOUND_SLUG
from app.tools.projects import list_projects
from app.tools.promote import promote_chat_to_project
from app.workspace.paths import (
    chat_attachment_path,
    chats_dir,
    docs_dir,
    unbound_chat_attachments_dir,
    unbound_chat_log_path,
    unbound_chat_meta_path,
    unbound_chats_root,
)
from app.workspace.staging import stage_file


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"
CID = "c_unbound00001"


class _FakeClient:
    def __init__(self, *, options: Any) -> None:
        self.options = options

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def query(self, prompt: Any) -> None:  # noqa: ARG002
        return None

    async def receive_response(self):
        if False:
            yield None  # pragma: no cover


def _make_service(workspace: Path) -> ChatService:
    return ChatService(workspace=workspace, provider=AsyncMock(),
                       agent_model="claude-sonnet-4-6")


def _events(chunks: list[str]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for ch in chunks:
        lines = ch.strip().split("\n")
        ev = next((ln[len("event:"):].strip() for ln in lines if ln.startswith("event:")), "")
        dat = next((ln[len("data:"):].strip() for ln in lines if ln.startswith("data:")), "{}")
        try:
            payload = json.loads(dat)
        except json.JSONDecodeError:
            payload = {}
        out.append((ev, payload))
    return out


async def test_unbound_text_only_turn_lands_under_chats_root(
    workspace: Path,
) -> None:
    """A plain-text turn at `slug='_chats'`: jsonl materialises at
    `_chats/<cid>.jsonl`; NO project is minted; NO `project_minted` event."""
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug=_UNBOUND_SLUG,
                chat_id=CID,
                user_message="hello",
                attachments=None,
            )
        ]
    events = _events(chunks)
    assert all(e[0] != "project_minted" for e in events), \
        f"unbound path must not mint a project; got {events!r}"
    # No project folders.
    projects = await list_projects(workspace)
    assert projects == []
    # Event log lives under `_chats/`.
    log = unbound_chat_log_path(workspace, CID)
    assert log.exists()
    first = json.loads(log.read_text().splitlines()[0])
    assert first == {"type": "user", "text": "hello"}


async def test_unbound_turn_with_stage_token_lands_in_unbound_attachments(
    workspace: Path,
) -> None:
    """A stage-token attachment on an unbound turn claims into
    `_chats/<cid>/attachments/`, NOT into any project's `docs/` (there is no
    project)."""
    staged = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug=_UNBOUND_SLUG,
                chat_id=CID,
                user_message="what is this?",
                attachments=[{"filename": "scan.pdf", "stage_token": staged["stage_token"]}],
            )
        ]
    events = _events(chunks)
    assert all(e[0] != "project_minted" for e in events)
    # Attachment moved into the unbound chat's dir.
    att_dir = unbound_chat_attachments_dir(workspace, CID)
    assert (att_dir / "scan.pdf").exists()
    assert (att_dir / "scan.pdf").read_bytes() == SAMPLE_PDF
    # No project was created.
    assert await list_projects(workspace) == []
    # User line persisted with source='chat'.
    first = json.loads(unbound_chat_log_path(workspace, CID).read_text().splitlines()[0])
    assert first["attachments"][0] == {"filename": "scan.pdf", "source": "chat"}


async def test_unbound_to_promoted_full_lifecycle(workspace: Path) -> None:
    """End-to-end: send an unbound turn (writes jsonl + meta + attachment),
    then promote — `_chats/<cid>.*` is gone, project has the full history,
    `list_projects` surfaces the project."""
    staged = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        async for _ in svc.chat_turn(
            slug=_UNBOUND_SLUG,
            chat_id=CID,
            user_message="ingest these",
            attachments=[{"filename": "scan.pdf", "stage_token": staged["stage_token"]}],
        ):
            pass

    out = await promote_chat_to_project(workspace, CID, name="invoice-set")
    new_slug = out["slug"]
    assert new_slug == "invoice-set"

    # `_chats/` slot is empty post-promote — tombstone in place, sources gone.
    assert unbound_chat_tombstone_path(workspace, CID).exists()
    assert not unbound_chat_log_path(workspace, CID).exists()
    assert not unbound_chat_meta_path(workspace, CID).exists()
    assert not (unbound_chats_root(workspace) / CID).exists()

    # Project has the full chat history.
    dst_log = chats_dir(workspace, new_slug) / f"{CID}.jsonl"
    assert dst_log.exists()
    events = [json.loads(ln) for ln in dst_log.read_text().splitlines() if ln.strip()]
    assert events[0]["type"] == "user"
    assert events[0]["text"] == "ingest these"

    # Attachment moved with the chat — NOT into docs/.
    assert chat_attachment_path(workspace, new_slug, CID, "scan.pdf").exists()
    if docs_dir(workspace, new_slug).exists():
        assert list(docs_dir(workspace, new_slug).glob("*.pdf")) == []

    # `list_projects` surfaces it (was hidden under `_chats/` before).
    projects = await list_projects(workspace)
    assert any(p["slug"] == new_slug for p in projects)


async def test_list_unbound_chats_reflects_lifecycle(workspace: Path) -> None:
    """Listing endpoint reflects current state: lists a freshly-minted chat
    by its meta sidecar, drops it after promote (which tombstones)."""
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, CID,
        first_user_message="initial",
        has_attachments=False,
    )
    await append_event(
        workspace, _UNBOUND_SLUG, CID, {"type": "user", "text": "initial"},
    )
    assert any(c["chat_id"] == CID for c in list_unbound_chats(workspace))

    await promote_chat_to_project(workspace, CID, name="bound-now")
    assert all(c["chat_id"] != CID for c in list_unbound_chats(workspace))
