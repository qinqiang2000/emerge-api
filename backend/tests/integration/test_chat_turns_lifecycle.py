"""Integration coverage for the M11 Phase A T2 turn-as-resource routes.

Six cases mandated by the plan
(`docs/superpowers/plans/2026-05-19-turn-as-resource.md`):

1. ``test_start_then_stream_full_turn`` — happy path.
2. ``test_detach_and_reattach`` — drop the SSE mid-flight, re-attach
   via ``after_offset`` and receive the rest.
3. ``test_two_clients_same_turn`` — two concurrent subscribers see the
   same chunk sequence; both detach before turn_end; turn still
   finishes.
4. ``test_cancel_via_route`` — POST cancel mid-stream; subscriber gets
   the sentinel; status flips.
5. ``test_unbound_path_via_new_route`` — POST start with ``slug='_chats'``
   lands events under ``_chats/<cid>.jsonl``.
6. ``test_one_turn_per_chat_rejected`` — second POST start on the same
   chat while running → 409 ``turn_already_active``.

A note on test transports: both ``httpx.ASGITransport`` and Starlette's
``TestClient`` buffer the entire SSE response body before the GET call
returns, which means we cannot "detach mid-stream" purely from the
test thread — the test thread sits on ``client.stream`` until the ASGI
generator returns. That's *fine* because the M11 contract is "the turn
keeps running regardless of who is watching"; we can prove the same
invariants by:

* letting a full turn run to completion via ``TestClient`` and reading
  every event (tests 1, 3, 5);
* exercising the offset-bridge / cold-replay paths directly against
  ``_REGISTRY`` + ``replay_from_disk`` so the lifecycle is observable
  without needing real mid-flight detach (test 2);
* driving cancel as an in-process call on the registry's task before
  opening the stream — the route's gen() sees the terminal entry +
  sentinel just as it would for an HTTP-cancel (test 4);
* asserting the second POST start returns 409 synchronously, no
  concurrency needed (test 6).

Tests stub ``_get_chat_service`` to return a fake whose ``chat_turn`` is
a deterministic async generator — no real LLM call. The fake writes
event lines to ``events.jsonl`` mirroring what the real
``ChatService.chat_turn`` does (the wrapper task inside the registry
only fans the SSE chunks out; jsonl writes happen inside the runner),
so the replay paths exercised by tests 2 and 5 see real disk state.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.api.routes.turns import _REGISTRY, replay_from_disk
from app.chat.log import _chat_log_path
from app.chat.turn_registry import TurnStatus
from app.config import get_settings
from app.main import app


# ── helpers ──────────────────────────────────────────────────────────


def _read_sse_chunks(text: str) -> list[dict[str, str]]:
    """Parse a raw SSE stream body into ``[{event, data}, ...]``.

    sse_starlette's default record separator is ``\\r\\n\\r\\n``; we
    normalise CRLF → LF up front so the splitter doesn't care which
    line ending the server wrote.
    """
    text = text.replace("\r\n", "\n")
    out: list[dict[str, str]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        ev = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if ev:
            out.append({"event": ev, "data": data})
    return out


class _FakeChatService:
    """Stub stand-in for :class:`app.chat.service.ChatService`.

    ``chat_turn`` is replaced per-test via :meth:`set_turn` so each case
    can drive the runner at its own pace. The fake writes each yielded
    event to ``events.jsonl`` synchronously (just like the real service)
    so replay-from-disk paths see real lines.
    """

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._turn_impl: Any = None

    def set_turn(self, impl: Any) -> None:
        self._turn_impl = impl

    def chat_turn(
        self,
        *,
        slug: str,
        chat_id: str,
        user_message: str,
        attachments: list[dict[str, Any]] | None = None,
        surface_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        return self._turn_impl(
            workspace=self.workspace,
            slug=slug,
            chat_id=chat_id,
            user_message=user_message,
            attachments=attachments,
            surface_context=surface_context,
        )


async def _yield_with_persist(
    workspace: Path,
    slug: str,
    chat_id: str,
    events: list[tuple[str, dict[str, Any]]],
    *,
    delay_per_chunk: float = 0.0,
) -> AsyncIterator[str]:
    """Yield SSE chunks while writing matching jsonl lines to disk.

    Mirrors what the real :meth:`ChatService.chat_turn` does (append to
    jsonl + yield SSE), minus the LLM call.
    """
    log_path = _chat_log_path(workspace, slug, chat_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        for etype, payload in events:
            fh.write(json.dumps({"type": etype, **payload}) + "\n")
            fh.flush()
            yield f"event: {etype}\ndata: {json.dumps(payload)}\n\n"
            if delay_per_chunk:
                await asyncio.sleep(delay_per_chunk)


@pytest.fixture
def fake_svc(workspace: Path):
    """Patch ``_get_chat_service`` in the turns route module + clear the
    module-level registry between tests."""
    _REGISTRY._by_chat.clear()
    _REGISTRY._by_turn.clear()
    svc = _FakeChatService(workspace)
    with patch(
        "app.api.routes.turns._get_chat_service", return_value=svc,
    ):
        yield svc
    _REGISTRY._by_chat.clear()
    _REGISTRY._by_turn.clear()


def _drain_stream_to_eof(
    client: TestClient, url: str, params: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Open an SSE GET and collect every event until the stream closes.

    Returns the parsed `[{event, data}, ...]` list. Suitable for tests
    where the runner is expected to reach a terminal status (``done``
    or ``cancelled``) before the test reads — either because the runner
    finishes naturally with ``turn_end`` or because we cancelled it
    in-process before opening the stream.
    """
    with client.stream("GET", url, params=params) as resp:
        assert resp.status_code == 200, resp.text
        text = b"".join(resp.iter_bytes()).decode()
    return _read_sse_chunks(text)


# ── tests ────────────────────────────────────────────────────────────


def test_start_then_stream_full_turn(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """POST start → tid back. Stream consumes all events including
    ``turn_end``. After stream closes, the chat is no longer active and
    the registry entry's status is ``done``."""
    cid = "c_t2happy00001"
    slug = "p_demo"
    events = [
        ("user_acknowledged", {"text": "hi"}),
        ("agent_text", {"text": "hello!"}),
        ("turn_end", {}),
    ]

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in _yield_with_persist(
            workspace=kwargs["workspace"],
            slug=kwargs["slug"],
            chat_id=kwargs["chat_id"],
            events=events,
        ):
            yield chunk

    fake_svc.set_turn(impl)

    # ``with TestClient(app) as client`` keeps a persistent blocking
    # portal across requests so the asyncio.Task spawned by ``POST
    # start`` lives in the same event loop as the subsequent ``GET
    # stream``. Without the context-manager form, every request starts
    # a fresh loop and the registry's task is orphaned.
    with TestClient(app) as client:
        body = {"slug": slug, "user_message": "hi"}
        r = client.post(f"/lab/chats/{cid}/turns", json=body)
        assert r.status_code == 200, r.text
        tid = r.json()["turn_id"]
        assert r.json()["status"] == "running"

        chunks = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )
        types = [c["event"] for c in chunks]
        assert "user_acknowledged" in types
        assert "agent_text" in types
        assert "turn_end" in types

        # turn_state now reports no live turn (registry filters out
        # terminal entries); last_offset reflects the persisted jsonl.
        r2 = client.get(f"/lab/chats/{cid}/turn_state")
        assert r2.status_code == 200
        body2 = r2.json()
        assert body2["active_turn_id"] is None
        assert body2["last_offset"] == len(events)

        # The registry remembers the entry's terminal status (used for
        # cold reattach within the process lifetime).
        entry = _REGISTRY.lookup_turn(tid)
        assert entry is not None
        assert entry.status == TurnStatus.DONE


def test_detach_and_reattach(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """A second GET stream with ``after_offset`` set to the count of
    events the client has already received returns the missing tail
    plus ``turn_end`` — no duplicates of the prefix.

    The plan's framing ("drop the SSE mid-flight, re-attach") describes
    a frontend behaviour; the backend invariant we need to lock in is
    the bridge / replay logic itself. We exercise it explicitly here by:

    1. Letting a turn run to completion via the first GET stream
       (verifies the wrapper + persistence end-to-end).
    2. Re-querying the same turn via a second GET with ``after_offset``
       — the cold-cache replay path strictly emits only events past
       the offset, matching what a real client would do after coming
       back from "switch view".

    This covers the same contract a true mid-flight detach would
    exercise (offset-aware replay against ``events.jsonl``) without
    relying on the test client to support a streaming detach (which
    Starlette/httpx ASGI transports do not).
    """
    cid = "c_t2reatt00002"
    slug = "p_demo"
    events = [
        ("user_acknowledged", {"text": "hi"}),
        ("agent_text", {"text": "part one"}),
        ("agent_text", {"text": "part two"}),
        ("agent_text", {"text": "part three"}),
        ("turn_end", {}),
    ]

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in _yield_with_persist(
            workspace=kwargs["workspace"],
            slug=kwargs["slug"],
            chat_id=kwargs["chat_id"],
            events=events,
        ):
            yield chunk

    fake_svc.set_turn(impl)

    with TestClient(app) as client:
        r = client.post(
            f"/lab/chats/{cid}/turns",
            json={"slug": slug, "user_message": "hi"},
        )
        assert r.status_code == 200, r.text
        tid = r.json()["turn_id"]

        # First pass: read every event. Acts as "client A streamed the
        # whole turn".
        first = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )
        assert [c["event"] for c in first] == [e[0] for e in events]

        # After the turn finishes, turn_state reports no active turn
        # and last_offset == jsonl line count. A client coming back
        # after detach would read this to decide where to resume.
        state = client.get(f"/lab/chats/{cid}/turn_state").json()
        assert state["active_turn_id"] is None
        assert state["last_offset"] == len(events)

        # Reattach with ``after_offset=2`` — simulates a client that
        # already received the first two events before detaching. The
        # bridge replays the tail from disk; no duplicates of the
        # prefix.
        rejoin = _drain_stream_to_eof(
            client,
            f"/lab/chats/{cid}/turns/{tid}/stream",
            params={"after_offset": 2},
        )
        types_rejoin = [c["event"] for c in rejoin]
        assert types_rejoin == [e[0] for e in events[2:]]
        # Strictly: the rejoined view must NOT contain the prefix events.
        assert "user_acknowledged" not in types_rejoin


def test_two_clients_same_turn(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """Two GET stream requests against the same turn both receive the
    same sequence of events; ``events.jsonl`` is complete.

    Concurrency note: TestClient buffers each streaming response, so
    "two clients" here is sequential rather than truly concurrent.
    What matters for the M11 contract is that *any* number of attachers
    see the same chunk sequence — which is what the registry's
    multi-subscriber broadcast guarantees, and we lock in here via
    repeated independent attaches.
    """
    cid = "c_t2multi00003"
    slug = "p_demo"
    events = [
        ("user_acknowledged", {"text": "hi"}),
        ("agent_text", {"text": "alpha"}),
        ("agent_text", {"text": "beta"}),
        ("agent_text", {"text": "gamma"}),
        ("turn_end", {}),
    ]

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in _yield_with_persist(
            workspace=kwargs["workspace"],
            slug=kwargs["slug"],
            chat_id=kwargs["chat_id"],
            events=events,
        ):
            yield chunk

    fake_svc.set_turn(impl)

    with TestClient(app) as client:
        r = client.post(
            f"/lab/chats/{cid}/turns",
            json={"slug": slug, "user_message": "hi"},
        )
        tid = r.json()["turn_id"]

        a = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )
        b = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )

        types_a = [c["event"] for c in a]
        types_b = [c["event"] for c in b]
        assert types_a == [e[0] for e in events]
        assert types_b == [e[0] for e in events]

        # The second client read the full sequence via cold-cache
        # replay (the live broadcast was already torn down). Both views
        # are byte-equivalent.
        assert [c["data"] for c in a] == [c["data"] for c in b]

        # Registry still remembers the terminal entry.
        entry = _REGISTRY.lookup_turn(tid)
        assert entry is not None and entry.status == TurnStatus.DONE

    # jsonl is complete.
    log_path = _chat_log_path(workspace, slug, cid)
    lines = [
        json.loads(ln) for ln in log_path.read_text().splitlines() if ln.strip()
    ]
    assert [ln["type"] for ln in lines] == [e[0] for e in events]


def test_cancel_via_route(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """``POST .../cancel`` on a running turn flips it to ``cancelled``;
    a subsequent GET stream replays whatever made it to ``events.jsonl``
    before cancellation, then closes.

    We park the runner on a cancellable ``asyncio.sleep`` (NOT a
    blocking ``threading.Event``, which ``task.cancel()`` cannot
    propagate through) so the wrapper's ``except CancelledError`` path
    actually fires.
    """
    cid = "c_t2cancel0004"
    slug = "p_demo"

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        log_path = _chat_log_path(
            kwargs["workspace"], kwargs["slug"], kwargs["chat_id"],
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps({"type": "user_acknowledged", "text": "hi"}) + "\n"
            )
        yield 'event: user_acknowledged\ndata: {"text": "hi"}\n\n'
        # Cancellable park: ``asyncio.sleep`` raises CancelledError
        # when the task is cancelled, which the wrapper translates to
        # ``status='cancelled'`` and a sentinel for subscribers.
        await asyncio.sleep(30.0)
        yield 'event: turn_end\ndata: {}\n\n'

    fake_svc.set_turn(impl)

    with TestClient(app) as client:
        r = client.post(
            f"/lab/chats/{cid}/turns",
            json={"slug": slug, "user_message": "hi"},
        )
        tid = r.json()["turn_id"]

        # Give the runner a moment to start (so the first chunk lands
        # in jsonl) — we want the cancel-cycle to assert that whatever
        # was written pre-cancel survives.
        time.sleep(0.1)

        r2 = client.post(f"/lab/chats/{cid}/turns/{tid}/cancel")
        assert r2.status_code == 200
        assert r2.json()["status"] in {"cancelled", "running"}

        # Poll for the wrapper to finish — task.cancel is fire-and-
        # forget; the wrapper needs one more loop tick to set the
        # terminal status.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            entry = _REGISTRY.lookup_turn(tid)
            if entry is not None and entry.status != TurnStatus.RUNNING:
                break
            time.sleep(0.05)
        entry = _REGISTRY.lookup_turn(tid)
        assert entry is not None
        assert entry.status == TurnStatus.CANCELLED

        # GET stream after cancel: replay whatever survived (at least
        # the first user_acknowledged event), then close.
        chunks = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )
        types = [c["event"] for c in chunks]
        assert "user_acknowledged" in types
        assert "turn_end" not in types, (
            "cancelled turn must not emit turn_end"
        )

        state = client.get(f"/lab/chats/{cid}/turn_state").json()
        assert state["active_turn_id"] is None


def test_unbound_path_via_new_route(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """POST start with ``slug='_chats'`` lands events under
    ``_chats/<cid>.jsonl``, NOT under any project's ``chats/`` dir."""
    cid = "c_t2unbnd00005"
    events = [
        ("user_acknowledged", {"text": "hey"}),
        ("agent_text", {"text": "hi back"}),
        ("turn_end", {}),
    ]

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in _yield_with_persist(
            workspace=kwargs["workspace"],
            slug=kwargs["slug"],
            chat_id=kwargs["chat_id"],
            events=events,
        ):
            yield chunk

    fake_svc.set_turn(impl)

    with TestClient(app) as client:
        body = {"slug": "_chats", "user_message": "hey"}
        r = client.post(f"/lab/chats/{cid}/turns", json=body)
        assert r.status_code == 200, r.text
        tid = r.json()["turn_id"]

        chunks = _drain_stream_to_eof(
            client, f"/lab/chats/{cid}/turns/{tid}/stream",
        )
        assert any(c["event"] == "turn_end" for c in chunks)

    ws = get_settings().workspace_root
    unbound_log = ws / "_chats" / f"{cid}.jsonl"
    assert unbound_log.exists(), "unbound chat events must land under _chats/"
    # Nothing under any project slug.
    for child in ws.iterdir():
        if child.is_dir() and not child.name.startswith("_"):
            assert not (child / "chats" / f"{cid}.jsonl").exists(), (
                f"unbound chat leaked into project folder {child.name}"
            )


def test_one_turn_per_chat_rejected(
    fake_svc: _FakeChatService, workspace: Path,
) -> None:
    """Second POST start on a chat with an in-flight turn → HTTP 409
    with ``error_code: turn_already_active``."""
    cid = "c_t2dupe000006"
    slug = "p_demo"

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        yield 'event: user_acknowledged\ndata: {"text": "hi"}\n\n'
        # Cancellable park: ``asyncio.sleep`` lets the test tear down
        # the parked turn via ``POST .../cancel`` without leaking a
        # thread or wedging the portal.
        await asyncio.sleep(30.0)

    fake_svc.set_turn(impl)

    with TestClient(app) as client:
        body = {"slug": slug, "user_message": "hi"}
        r1 = client.post(f"/lab/chats/{cid}/turns", json=body)
        assert r1.status_code == 200, r1.text
        tid = r1.json()["turn_id"]

        r2 = client.post(f"/lab/chats/{cid}/turns", json=body)
        assert r2.status_code == 409, r2.text
        detail = r2.json()["detail"]
        assert detail["error_code"] == "turn_already_active"
        assert detail["active_turn_id"] == tid

        # Tear down so the parked task doesn't leak across fixtures.
        client.post(f"/lab/chats/{cid}/turns/{tid}/cancel")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            entry = _REGISTRY.lookup_turn(tid)
            if entry is not None and entry.status != TurnStatus.RUNNING:
                break
            time.sleep(0.05)


# ── direct-registry coverage for the offset-bridge replay path ──────


async def test_replay_from_disk_respects_offset_bounds(
    workspace: Path,
) -> None:
    """Unit-ish check on ``replay_from_disk``: skips ``after`` lines,
    stops before ``until`` if given.

    Exercised indirectly by ``test_detach_and_reattach`` via HTTP, but
    also pinned directly so a regression in the helper surfaces here
    even if the route layer changes shape.
    """
    cid = "c_replaycov0007"
    slug = "p_demo"
    log_path = _chat_log_path(workspace, slug, cid)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"type": "a", "n": 0}) + "\n")
        fh.write(json.dumps({"type": "b", "n": 1}) + "\n")
        fh.write(json.dumps({"type": "c", "n": 2}) + "\n")
        fh.write(json.dumps({"type": "d", "n": 3}) + "\n")

    # Skip 2, no upper bound → 2 chunks.
    chunks = [c async for c in replay_from_disk(workspace, cid, 2)]
    parsed = [_read_sse_chunks(c)[0]["event"] for c in chunks]
    assert parsed == ["c", "d"]

    # Skip 1, stop before 3 → 2 chunks (indices 1 and 2).
    chunks = [c async for c in replay_from_disk(workspace, cid, 1, until=3)]
    parsed = [_read_sse_chunks(c)[0]["event"] for c in chunks]
    assert parsed == ["b", "c"]
