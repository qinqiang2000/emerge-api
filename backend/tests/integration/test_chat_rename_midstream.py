"""Mid-turn rename must NOT split chat history across two dirs.

Reproduces and pins the dogfood bug: agent calls `rename_project` between
chat_turn's two append_event passes. Without the pid-anchored slug
resolution, post-rename appends mkdir the OLD slug path again, leaving a
husk with half the events and stranding the conversation.

Also pins the new SSE: chat_turn emits `project_renamed` so the frontend
can re-point selectedSlug (and thus the URL) when the agent renames a
project mid-turn.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from claude_agent_sdk import AssistantMessage, TextBlock, ToolUseBlock, UserMessage

from app.chat.service import ChatService
from app.tools.projects import rename_project
from app.workspace.paths import chats_dir, project_json_path


CID = "c_abc123def456"


class _RenameMidStreamClient:
    """SDK stand-in that yields a text block, runs `rename_project` against
    the workspace (simulating the agent doing it), then yields another text
    block. The first text block is logged under the original slug; the
    second must land under the renamed slug — that's the contract.
    """

    def __init__(self, *, options: Any, workspace: Path, old_slug: str, new_name: str) -> None:
        self.options = options
        self._workspace = workspace
        self._old_slug = old_slug
        self._new_name = new_name

    async def __aenter__(self) -> "_RenameMidStreamClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def query(self, prompt: Any) -> None:  # noqa: ARG002
        return None

    async def receive_response(self):
        # First message — recorded under the old slug.
        yield AssistantMessage(
            content=[TextBlock(text="before rename")], model="x", parent_tool_use_id=None,
        )
        # Mid-stream: simulate the agent's rename_project tool call by running
        # it directly (the tool dispatcher is bypassed here — we are testing
        # chat_turn's slug-resolution, not the SDK plumbing).
        await rename_project(self._workspace, self._old_slug, name=self._new_name)
        # Emit the tool_use + a tool result echo, then a follow-up text.
        yield AssistantMessage(
            content=[
                ToolUseBlock(id="t_1", name="mcp__emerge_tools__rename_project",
                             input={"slug": self._old_slug, "name": self._new_name}),
            ],
            model="x",
            parent_tool_use_id=None,
        )
        yield UserMessage(
            content=[],
            parent_tool_use_id=None,
        )
        yield AssistantMessage(
            content=[TextBlock(text="after rename")], model="x", parent_tool_use_id=None,
        )


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


async def test_midstream_rename_lands_events_under_new_slug(workspace: Path) -> None:
    """All chat events — pre- AND post-rename — must end up in the new
    slug's chats/ dir. The pre-rename dir gets atomically moved by
    `os.rename` inside `rename_project`, so the OLD slug path must NOT be
    recreated by subsequent appends."""
    from app.tools.projects import create_project

    proj = await create_project(workspace, name="placeholder")
    old_slug = proj["slug"]

    def _make_fake(*, options: Any) -> _RenameMidStreamClient:
        return _RenameMidStreamClient(
            options=options,
            workspace=workspace,
            old_slug=old_slug,
            new_name="renamed-target",
        )

    svc = ChatService(
        workspace=workspace,
        provider=AsyncMock(),
        agent_model="claude-sonnet-4-6",
    )
    with patch("app.chat.service.ClaudeSDKClient", _make_fake):
        chunks = [
            c async for c in svc.chat_turn(
                slug=old_slug,
                chat_id=CID,
                user_message="rename us please",
            )
        ]
    events = _events(chunks)

    # Filesystem assertion: the new dir has the chat log, the old slug path
    # was NOT recreated as a husk.
    new_slug = "renamed-target"
    assert (workspace / new_slug / "chats" / f"{CID}.jsonl").exists()
    # The old slug dir, if it exists at all, must NOT contain a chats subdir
    # (rename moves the whole tree; if anything is at the old path it would
    # be a recreated husk).
    old_chats = workspace / old_slug / "chats"
    assert not old_chats.exists(), (
        f"old slug chats path should not be recreated post-rename; "
        f"found {list(old_chats.iterdir()) if old_chats.exists() else None}"
    )

    # The full chat log under the new slug contains BOTH the pre- and
    # post-rename agent_text events.
    log_lines = (workspace / new_slug / "chats" / f"{CID}.jsonl").read_text().splitlines()
    agent_texts = [
        json.loads(ln) for ln in log_lines
        if json.loads(ln).get("type") == "agent_text"
    ]
    texts = [e["text"] for e in agent_texts]
    assert "before rename" in texts and "after rename" in texts, texts

    # SSE: project_renamed must fire so the frontend can update URL/store.
    renamed = [e for e in events if e[0] == "project_renamed"]
    assert len(renamed) == 1, f"expected one project_renamed event, got {events!r}"
    assert renamed[0][1] == {"old_slug": old_slug, "new_slug": new_slug}


async def test_no_rename_no_project_renamed_event(workspace: Path) -> None:
    """Sanity guard: when slug is stable across a turn, project_renamed
    must NOT fire (would noisily kick the frontend's URL sync for nothing)."""
    from app.tools.projects import create_project

    proj = await create_project(workspace, name="stable")
    slug = proj["slug"]

    class _Quiet:
        def __init__(self, *, options: Any) -> None:
            self.options = options

        async def __aenter__(self) -> "_Quiet":
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def query(self, prompt: Any) -> None:  # noqa: ARG002
            return None

        async def receive_response(self):
            if False:
                yield None  # pragma: no cover

    svc = ChatService(
        workspace=workspace,
        provider=AsyncMock(),
        agent_model="claude-sonnet-4-6",
    )
    with patch("app.chat.service.ClaudeSDKClient", _Quiet):
        chunks = [
            c async for c in svc.chat_turn(
                slug=slug, chat_id=CID, user_message="hello",
            )
        ]
    events = _events(chunks)
    assert not any(e[0] == "project_renamed" for e in events)
    # project.json untouched.
    assert json.loads(project_json_path(workspace, slug).read_text())["slug"] == slug
