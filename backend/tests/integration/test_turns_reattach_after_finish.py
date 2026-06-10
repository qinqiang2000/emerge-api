"""Cosmetic-bug regression: reattach to a terminal turn must return 200.

When a client re-attaches a `GET .../turns/{tid}/stream` to a turn that has
already reached a terminal status (typically because the original SSE
fetched `turn_state` first, saw `status=running`, then by the time the
stream request landed the turn had finished), the route's ``gen()``
generator yields zero items — sse_starlette closes with HTTP 503 instead
of a clean 200 + empty SSE body.

The data lands correctly via jsonl hydrate so the user never notices, but
the HTTP contract should be 200 for "you just attached to something that
already happened" — empty bridge replay + immediate sentinel = "no live
events" is not an error.

Two scenarios both must end with HTTP 200:

1. **Hot cache, terminal status.** Entry still exists in the registry,
   ``status == done``, and the client requests with ``after_offset ==
   entry.last_offset`` (i.e. they already hydrated jsonl up to the end).
   Bridge slice is empty; subscribe immediately yields the sentinel.
   Today: 503. Expected: 200.

2. **Cold cache.** Entry is gone from the registry — ``lookup_turn``
   returns ``None``. Client passes ``after_offset`` past the persisted
   jsonl tail (or jsonl doesn't exist for that turn). ``replay_from_disk``
   yields nothing. Today: 503. Expected: 200.

Both pin the same underlying fix: synthesise at least one chunk
(a ``turn_end`` event) so sse_starlette commits a 200 status line.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.routes.turns import _REGISTRY
from app.chat.log import _chat_log_path
from app.chat.turn_registry import TurnStatus
from app.main import app


# ── helpers (lightweight copies of the lifecycle-test stubs) ─────────


class _FakeChatService:
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
        # Must mirror the real ``ChatService.chat_turn`` signature — the
        # runner factory passes ``interface=`` explicitly; a mismatch
        # raises TypeError inside the registry wrapper task (see the
        # lifecycle-test fake for the deadlock story).
        interface: str = "browser",
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
) -> AsyncIterator[str]:
    log_path = _chat_log_path(workspace, slug, chat_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        for etype, payload in events:
            fh.write(json.dumps({"type": etype, **payload}) + "\n")
            fh.flush()
            yield f"event: {etype}\ndata: {json.dumps(payload)}\n\n"


def _read_sse_chunks(text: str) -> list[dict[str, str]]:
    """Parse a raw SSE stream body into ``[{event, data}, ...]``.

    Mirrors the helper in ``test_chat_turns_lifecycle`` — normalise CRLF
    so the splitter doesn't care about the wire format.
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


# ── tests ────────────────────────────────────────────────────────────


def test_reattach_hot_cache_terminal_returns_200(workspace: Path) -> None:
    """After a turn finishes, attaching again with ``after_offset`` ==
    ``entry.last_offset`` must return 200 (not 503) with a synthetic
    ``turn_end`` event so the client knows the turn is over.
    """
    cid = "c_rehot0000001"
    slug = "p_demo"
    events = [
        ("user_acknowledged", {"text": "hi"}),
        ("agent_text", {"text": "ok"}),
        ("turn_end", {}),
    ]

    _REGISTRY._by_chat.clear()
    _REGISTRY._by_turn.clear()
    svc = _FakeChatService(workspace)

    async def impl(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in _yield_with_persist(
            workspace=kwargs["workspace"],
            slug=kwargs["slug"],
            chat_id=kwargs["chat_id"],
            events=events,
        ):
            yield chunk

    svc.set_turn(impl)

    try:
        with patch(
            "app.api.routes.turns._get_chat_service", return_value=svc,
        ), TestClient(app) as client:
            r = client.post(
                f"/lab/chats/{cid}/turns",
                json={"slug": slug, "user_message": "hi"},
            )
            assert r.status_code == 200, r.text
            tid = r.json()["turn_id"]

            # Drain the live stream to completion — entry flips to DONE.
            with client.stream(
                "GET", f"/lab/chats/{cid}/turns/{tid}/stream",
            ) as resp:
                _ = b"".join(resp.iter_bytes())

            entry = _REGISTRY.lookup_turn(tid)
            assert entry is not None
            assert entry.status == TurnStatus.DONE

            # Re-attach with after_offset == last_offset → bridge slice
            # empty, subscribe gets immediate sentinel. Before the fix:
            # sse_starlette closes the empty generator with 503.
            with client.stream(
                "GET",
                f"/lab/chats/{cid}/turns/{tid}/stream",
                params={"after_offset": entry.last_offset},
            ) as resp:
                body_bytes = b"".join(resp.iter_bytes())
                assert resp.status_code == 200, (
                    f"reattach to terminal turn must return 200, got "
                    f"{resp.status_code}: {body_bytes!r}"
                )

            # Body should carry a synthetic turn_end so the client knows
            # the turn is over without round-tripping turn_state.
            chunks = _read_sse_chunks(body_bytes.decode())
            types = [c["event"] for c in chunks]
            assert "turn_end" in types, (
                f"reattach must surface a turn_end event, got {chunks!r}"
            )
    finally:
        _REGISTRY._by_chat.clear()
        _REGISTRY._by_turn.clear()


def test_reattach_cold_cache_unknown_turn_returns_200(workspace: Path) -> None:
    """``GET .../turns/{tid}/stream`` for a turn that was evicted (or
    never existed) must return 200 with a synthetic turn_end, not 503
    from sse_starlette's empty-generator fallback.

    Simulates the cold-cache path by:
      * never starting a turn for ``tid``,
      * passing a stale ``after_offset`` (no jsonl file exists for the
        chat), so ``replay_from_disk`` yields zero chunks.
    """
    _REGISTRY._by_chat.clear()
    _REGISTRY._by_turn.clear()

    cid = "c_recold000001"
    tid = "deadbeef9999"  # never registered

    try:
        with TestClient(app) as client:
            with client.stream(
                "GET",
                f"/lab/chats/{cid}/turns/{tid}/stream",
                params={"after_offset": 0},
            ) as resp:
                body_bytes = b"".join(resp.iter_bytes())
                assert resp.status_code == 200, (
                    f"cold-cache reattach must return 200, got "
                    f"{resp.status_code}: {body_bytes!r}"
                )

            chunks = _read_sse_chunks(body_bytes.decode())
            types = [c["event"] for c in chunks]
            assert "turn_end" in types, (
                f"cold-cache reattach must surface a turn_end event, "
                f"got {chunks!r}"
            )
    finally:
        _REGISTRY._by_chat.clear()
        _REGISTRY._by_turn.clear()
