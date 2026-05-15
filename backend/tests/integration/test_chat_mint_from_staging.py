"""Empty-hero drop flow: chat_turn auto-mints a project + claims staged files.

When the frontend submits with `project_id='p_unset'` and at least one
attachment carrying a `stage_token`, the chat service must:

1. Mint a fresh project (placeholder name like `Chat-…` — signals
   "conversational scratch, not a curated set").
2. Move each staged file into the new project's
   `chats/<chat_id>/attachments/` (NOT into `docs/` — that requires an
   explicit `promote_attachment_to_docs` call).
3. Emit a `project_minted` SSE event so the frontend can flip `selectedId`,
   persist `activeChatId` under the new pid, and refresh stores.
4. Append the user line under the new pid with `attachments[i].source='chat'`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from app.chat.service import ChatService
from app.workspace.paths import (
    chat_attachments_dir,
    chats_dir,
    docs_dir,
    docs_meta_dir,
    project_json_path,
)
from app.workspace.staging import stage_file, stage_dir


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"
CID = "c_abc123def456"


class _FakeClient:
    """Async-context-manager stand-in for ClaudeSDKClient — yields nothing."""

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
            yield None  # pragma: no cover  — keep this an async generator


def _make_service(workspace: Path) -> ChatService:
    return ChatService(
        workspace=workspace,
        provider=AsyncMock(),
        agent_model="claude-sonnet-4-6",
    )


def _events(chunks: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Parse `event: x\\ndata: y\\n\\n` chunks into (event, data) pairs."""
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


async def test_p_unset_with_stage_token_mints_project_and_claims_file(
    workspace: Path,
) -> None:
    """The whole happy path: one PDF staged, one chat turn with stage_token,
    project minted as `Chat-…`, file moved into chat attachments (NOT docs/),
    project_minted SSE emitted, persisted attachment carries source='chat'."""
    staged = await stage_file(workspace, SAMPLE_PDF, "invoice.pdf")
    token = staged["stage_token"]

    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug="p_unset",
                chat_id=CID,
                user_message="/init pull these",
                attachments=[{"filename": "invoice.pdf", "stage_token": token}],
            )
        ]
    events = _events(chunks)
    minted = [e for e in events if e[0] == "project_minted"]
    assert len(minted) == 1, f"expected exactly one project_minted event; got {events!r}"
    payload = minted[0][1]
    new_slug = payload["slug"]
    assert new_slug == payload["project_id"], "legacy back-compat key must match slug"
    assert payload["pid"].startswith("p_"), f"pid must be the p_xxx audit anchor: {payload!r}"
    name = payload["name"]
    assert name.startswith("Chat-"), f"placeholder must be Chat-…, got {name!r}"
    assert new_slug.startswith("chat-"), new_slug

    # Project exists on disk under the new slug.
    blob = json.loads(project_json_path(workspace, new_slug).read_text())
    assert blob["name"] == name
    assert blob["project_id"] == payload["pid"]

    # File landed in chat attachments, NOT in docs/.
    att_files = [
        p for p in chat_attachments_dir(workspace, new_slug, CID).iterdir() if p.is_file()
    ]
    assert [p.name for p in att_files] == ["invoice.pdf"]
    assert att_files[0].read_bytes() == SAMPLE_PDF
    assert not docs_dir(workspace, new_slug).exists() or not list(
        docs_dir(workspace, new_slug).glob("*.pdf")
    ), "paste/drop must not pollute docs/"
    assert not docs_meta_dir(workspace, new_slug).exists() or not list(
        docs_meta_dir(workspace, new_slug).glob("*.json")
    ), "no docs sidecar for chat attachments"
    assert not stage_dir(workspace, token).exists()  # type: ignore[arg-type]

    # User line was logged under the *new* slug with source='chat'.
    log_path = chats_dir(workspace, new_slug) / f"{CID}.jsonl"
    assert log_path.exists()
    first_line = json.loads(log_path.read_text().splitlines()[0])
    assert first_line["type"] == "user"
    assert first_line["attachments"][0] == {
        "filename": "invoice.pdf", "source": "chat",
    }
    assert "stage_token" not in first_line["attachments"][0]


async def test_p_unset_renames_placeholder_to_chat_prefix(workspace: Path) -> None:
    """Placeholder uses `Chat-` prefix (not the legacy `Untitled-`)."""
    staged = await stage_file(workspace, SAMPLE_PDF, "invoice.pdf")
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug="p_unset",
                chat_id=CID,
                user_message="/init",
                attachments=[{"filename": "invoice.pdf", "stage_token": staged["stage_token"]}],
            )
        ]
    events = _events(chunks)
    minted = next(e[1] for e in events if e[0] == "project_minted")
    assert minted["name"].startswith("Chat-")
    assert not minted["name"].startswith("Untitled-")


async def test_mint_files_do_not_enter_docs_dir(workspace: Path) -> None:
    """Negative assertion: after empty-hero paste, `docs/` is either missing
    or empty. Promotion is the only path into `docs/`."""
    staged = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug="p_unset",
                chat_id=CID,
                user_message="what's this?",
                attachments=[{"filename": "scan.pdf", "stage_token": staged["stage_token"]}],
            )
        ]
    events = _events(chunks)
    new_slug = next(e[1]["slug"] for e in events if e[0] == "project_minted")
    docs_d = docs_dir(workspace, new_slug)
    if docs_d.exists():
        assert [p.name for p in docs_d.iterdir() if p.is_file()] == []


async def test_p_unset_plain_text_still_mints_placeholder(workspace: Path) -> None:
    """Plain-text empty-hero turn (no attachments) must STILL mint a
    placeholder project so chat events never write to `workspace/p_unset/`.

    Earlier behaviour gated the mint on stage_token attachments; that left
    an unlistable `workspace/p_unset/chats/<cid>/events.jsonl` orphan every
    time a user typed text without dropping files. The new contract: any
    `slug == 'p_unset'` turn mints, regardless of attachments.
    """
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug="p_unset",
                chat_id=CID,
                user_message="hello",
                attachments=None,
            )
        ]
    events = _events(chunks)
    minted = [e for e in events if e[0] == "project_minted"]
    assert len(minted) == 1, f"expected one project_minted, got {events!r}"
    new_slug = minted[0][1]["slug"]
    assert new_slug.startswith("chat-")
    # Chat log lives under the new slug, NOT under p_unset/.
    assert (chats_dir(workspace, new_slug) / f"{CID}.jsonl").exists()
    assert not (workspace / "p_unset").exists()


async def test_unknown_stage_token_dropped_silently(workspace: Path) -> None:
    """A stale / unknown stage_token doesn't fail the whole turn — the agent
    just sees one fewer attachment. The project still mints because at least
    one stage_token was present in the request (load-bearing for the
    'frontend retried, the network ate one of the staging POSTs' case)."""
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                slug="p_unset",
                chat_id=CID,
                user_message="/init",
                attachments=[
                    {"filename": "ghost.pdf", "stage_token": "st_deadbeefdeadbeef"},
                ],
            )
        ]
    events = _events(chunks)
    minted = [e for e in events if e[0] == "project_minted"]
    assert len(minted) == 1
    new_slug = minted[0][1]["slug"]
    # No docs moved (the token didn't exist), but the project itself is real.
    # `docs/` may not even have been created yet; tolerate either state.
    docs_d = docs_dir(workspace, new_slug)
    if docs_d.exists():
        assert [p.name for p in docs_d.iterdir() if p.is_file()] == []
