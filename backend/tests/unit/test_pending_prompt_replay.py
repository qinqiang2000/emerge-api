"""A turn blocked on a permission card must survive losing its stream.

Prod incident 2026-08-14 (chat ``c_4278ac030800``): the agent asked for
permission to run a Bash command outside the team workspace, the user's SSE
stream dropped before answering, and the chat was dead from then on — every
message came back 409 ``turn_already_active``.

The deadlock is structural, not a race:

* ``permission_request`` / ``ask_user_request`` are the only turn events that
  are never written to ``events.jsonl`` — they exist only on the wire.
* The turn cannot finish until the future is resolved.
* The only thing that resolves a stranded future is ``cancel_pending``, which
  runs **at turn end**.

So "card lost" == "turn wedged forever". These tests pin the fix: the pending
prompt is retained with its payload, and every fresh subscriber gets it
replayed.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from app.api.routes.turns import _attach_and_stream
from app.chat.ask_user import (
    cancel_pending_ask_user,
    request_user_answer,
    resolve_user_answer,
)
from app.chat.pending import snapshot_pending
from app.chat.permissions import (
    cancel_pending,
    request_permission,
    resolve_permission,
)
from app.chat.turn_registry import TurnRegistry


async def _drain_writer(_etype: str, _payload: dict[str, Any]) -> None:
    """An sse_writer whose client is already gone — the exact situation the
    replay exists for."""
    return None


# ── registry-level ───────────────────────────────────────────────────


async def test_pending_permission_is_snapshotable_until_resolved() -> None:
    cid = "c_pend_perm01"
    task = asyncio.create_task(
        request_permission(
            chat_id=cid,
            tool_name="Bash",
            tool_input={"command": "curl https://example.com"},
            reason="Command performs a network operation.",
            sse_writer=_drain_writer,
        )
    )
    # Let the gate register + emit before we look.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    pending = snapshot_pending(cid)
    assert len(pending) == 1
    etype, payload = pending[0]
    assert etype == "permission_request"
    assert payload["tool_name"] == "Bash"
    # The payload is the *same* frame the live client would have received —
    # replay must be a re-send, not a reconstruction.
    assert payload["reason"].startswith("Command performs")

    assert await resolve_permission(
        chat_id=cid, request_id=payload["request_id"], decision="approve",
    )
    result = await task
    assert result.__class__.__name__ == "PermissionResultAllow"
    assert snapshot_pending(cid) == []


async def test_pending_ask_user_is_snapshotable_until_resolved() -> None:
    cid = "c_pend_ask001"
    task = asyncio.create_task(
        request_user_answer(
            chat_id=cid,
            questions=[{"question": "Which model?", "options": [{"label": "flash"}]}],
            sse_writer=_drain_writer,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    pending = snapshot_pending(cid)
    assert len(pending) == 1
    etype, payload = pending[0]
    assert etype == "ask_user_request"
    assert payload["questions"][0]["question"] == "Which model?"

    assert await resolve_user_answer(
        chat_id=cid,
        request_id=payload["request_id"],
        answers=[{"question_index": 0, "selected": []}],
    )
    assert (await task)["ok"] is True
    assert snapshot_pending(cid) == []


async def test_turn_end_cancel_clears_the_snapshot() -> None:
    """The turn-end sweep still owns the last word — a prompt must never
    outlive the turn that raised it."""
    cid = "c_pend_cancel"
    perm = asyncio.create_task(
        request_permission(
            chat_id=cid,
            tool_name="WebFetch",
            tool_input={"url": "https://x"},
            reason="network",
            sse_writer=_drain_writer,
        )
    )
    ask = asyncio.create_task(
        request_user_answer(
            chat_id=cid, questions=[{"question": "q", "options": []}],
            sse_writer=_drain_writer,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(snapshot_pending(cid)) == 2

    await cancel_pending(cid)
    await cancel_pending_ask_user(cid)
    assert snapshot_pending(cid) == []
    assert (await perm).__class__.__name__ == "PermissionResultDeny"
    assert (await ask)["ok"] is False


# ── route-level: the replay itself ───────────────────────────────────


@pytest.mark.timeout(10)
async def test_attach_replays_the_pending_card(workspace: Path) -> None:
    """A client attaching to a running turn gets the outstanding card back.

    This is the whole fix: without it the second (or reloaded) client sees a
    turn that is running, produces nothing, and can never be answered.
    """
    cid = "c_pend_attach"
    registry = TurnRegistry()
    release = asyncio.Event()

    async def runner() -> AsyncIterator[str]:
        yield "event: agent_text\ndata: {}\n\n"
        await release.wait()

    entry = await registry.start(
        chat_id=cid, slug="p_demo", runner_factory=runner,
    )
    perm = asyncio.create_task(
        request_permission(
            chat_id=cid,
            tool_name="Bash",
            tool_input={"command": "find /root -name '*trash*'"},
            reason="Command touches a path outside the workspace.",
            sse_writer=_drain_writer,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    resp = _attach_and_stream(
        cid=cid, tid=entry.turn_id, after_offset=0, registry=registry,
    )
    it = resp.body_iterator
    first = await it.__anext__()
    assert first["event"] == "permission_request"
    payload = json.loads(first["data"])
    assert payload["tool_name"] == "Bash"

    # Answering the replayed card releases the turn — the whole point.
    assert await resolve_permission(
        chat_id=cid, request_id=payload["request_id"], decision="approve",
    )
    assert (await perm).__class__.__name__ == "PermissionResultAllow"
    release.set()
    # Drain to the sentinel so the generator (and its subscription) closes.
    async for _ in it:
        pass
    await entry.task  # type: ignore[arg-type]
