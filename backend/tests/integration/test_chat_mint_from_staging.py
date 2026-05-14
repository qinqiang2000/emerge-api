"""Empty-hero drop flow: chat_turn auto-mints a project + claims staged files.

When the frontend submits with `project_id='p_unset'` and at least one
attachment carrying a `stage_token`, the chat service must:

1. Mint a fresh project (placeholder name like `Untitled-…`).
2. Move each staged file into the new project's `docs/` via the normal
   `upload_doc` pipeline (file → `docs/<filename>`, sidecar →
   `docs/.meta/<filename>.json`) and rewrite each attachment to
   `{filename}` only — the post-`d_xxx` doc handle.
3. Emit a `project_minted` SSE event so the frontend can flip `selectedId`,
   persist `activeChatId` under the new pid, and refresh stores.
4. Append the user line under the new pid (no post-hoc chat migration).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from app.chat.service import ChatService
from app.workspace.paths import chats_dir, docs_dir, docs_meta_dir, project_json_path
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
    project minted, file moved into docs/, project_minted SSE emitted."""
    staged = await stage_file(workspace, SAMPLE_PDF, "invoice.pdf")
    token = staged["stage_token"]

    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                project_id="p_unset",
                chat_id=CID,
                user_message="/init pull these",
                attachments=[{"filename": "invoice.pdf", "stage_token": token}],
            )
        ]
    events = _events(chunks)
    minted = [e for e in events if e[0] == "project_minted"]
    assert len(minted) == 1, f"expected exactly one project_minted event; got {events!r}"
    new_pid = minted[0][1]["project_id"]
    name = minted[0][1]["name"]
    assert new_pid.startswith("p_")
    assert name.startswith("Untitled-")

    # Project exists on disk under the new pid.
    blob = json.loads(project_json_path(workspace, new_pid).read_text())
    assert blob["name"] == name

    # Staged file moved into the new project's docs/, sidecar landed in
    # `docs/.meta/`, staging dir gone.
    doc_files = [p for p in docs_dir(workspace, new_pid).iterdir() if p.is_file()]
    assert [p.name for p in doc_files] == ["invoice.pdf"]
    assert doc_files[0].read_bytes() == SAMPLE_PDF
    doc_metas = list(docs_meta_dir(workspace, new_pid).glob("*.json"))
    assert len(doc_metas) == 1
    moved_meta = json.loads(doc_metas[0].read_text())
    assert moved_meta["filename"] == "invoice.pdf"
    assert moved_meta["original_name"] == "invoice.pdf"
    assert not stage_dir(workspace, token).exists()  # type: ignore[arg-type]

    # User line was logged under the *new* pid (no p_unset leftover).
    log_path = chats_dir(workspace, new_pid) / f"{CID}.jsonl"
    assert log_path.exists()
    first_line = json.loads(log_path.read_text().splitlines()[0])
    assert first_line["type"] == "user"
    # The attachments persisted to the chat log carry only `filename` — we
    # strip `stage_token` at the persist boundary, and there is no `doc_id`
    # in the filename-native world.
    assert first_line["attachments"][0] == {"filename": "invoice.pdf"}
    assert "stage_token" not in first_line["attachments"][0]
    assert "doc_id" not in first_line["attachments"][0]


async def test_p_unset_without_stage_token_no_mint(workspace: Path) -> None:
    """If attachments lack stage_token, the chat stays in p_unset land —
    no mint, no project_minted event. The existing legacy behaviour."""
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                project_id="p_unset",
                chat_id=CID,
                user_message="hello",
                attachments=None,
            )
        ]
    events = _events(chunks)
    assert not any(e[0] == "project_minted" for e in events)
    # Chat log lives under p_unset/, not under any minted pid.
    assert (chats_dir(workspace, "p_unset") / f"{CID}.jsonl").exists()


async def test_unknown_stage_token_dropped_silently(workspace: Path) -> None:
    """A stale / unknown stage_token doesn't fail the whole turn — the agent
    just sees one fewer attachment. The project still mints because at least
    one stage_token was present in the request (load-bearing for the
    'frontend retried, the network ate one of the staging POSTs' case)."""
    svc = _make_service(workspace)
    with patch("app.chat.service.ClaudeSDKClient", _FakeClient):
        chunks = [
            c async for c in svc.chat_turn(
                project_id="p_unset",
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
    new_pid = minted[0][1]["project_id"]
    # No docs moved (the token didn't exist), but the project itself is real.
    # `docs/` may not even have been created yet; tolerate either state.
    docs_d = docs_dir(workspace, new_pid)
    if docs_d.exists():
        assert [p.name for p in docs_d.iterdir() if p.is_file()] == []
