"""Pending user-prompt registry — the noun behind ``permissions`` and
``ask_user``.

Both modules block a running turn on a future keyed by
``(chat_id, request_id)`` and unblock it from an HTTP route. They used to
carry a private copy of that registry each; this module owns the one copy
and adds the piece neither had: **the SSE payload is kept next to the
future**, so a client that (re)attaches mid-prompt can be handed the card
again.

Why that matters (prod incident 2026-08-14, chat ``c_4278ac030800``):

    permission_request / ask_user_request are the only turn events that are
    never written to ``events.jsonl`` — they are pure SSE. The turn cannot
    finish until the user answers, and the only thing that resolves a
    stranded future is ``cancel_pending`` … which runs *at turn end*. So a
    reload / dropped stream while a permission card was on screen deadlocked
    the turn forever: the card was gone, the future was never resolved, the
    turn stayed ``running``, and every later message got 409
    ``turn_already_active`` until the backend was restarted.

Keeping the payload lets ``GET /lab/chats/{cid}/turns/{tid}/stream`` replay
outstanding prompts to every fresh subscriber, which turns "reload = wedged
chat" into "reload = the card comes back".

The registry is process-local (same lifetime as ``TurnRegistry``) — a
backend restart drops both the futures and the turns they belong to.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any


__all__ = ["PendingPrompt", "PendingPrompts", "snapshot_pending"]


@dataclass
class PendingPrompt:
    """One outstanding question to the user.

    ``event_type`` + ``payload`` are exactly what was written to the SSE
    stream when the prompt was raised, so replaying is a byte-identical
    re-send rather than a reconstruction. ``future`` is what the tool /
    permission gate is awaiting.
    """

    event_type: str
    payload: dict[str, Any]
    future: asyncio.Future[dict[str, Any]] = field(repr=False)


class PendingPrompts:
    """Registry of in-flight prompts for one event type.

    One instance per prompt flavour (``permission_request``,
    ``ask_user_request``); both register themselves in
    :data:`_REGISTRIES` so :func:`snapshot_pending` can answer "what is
    this chat waiting on?" across flavours in stream order.
    """

    def __init__(self, event_type: str) -> None:
        self.event_type = event_type
        self._items: dict[tuple[str, str], PendingPrompt] = {}
        self._lock = asyncio.Lock()
        _REGISTRIES.append(self)

    async def register(
        self, *, chat_id: str, payload_for: Any
    ) -> tuple[str, dict[str, Any], asyncio.Future[dict[str, Any]]]:
        """Mint a ``request_id``, build the SSE payload, park a future.

        Returns ``(request_id, payload, future)``. ``payload_for`` is a
        callable taking the fresh ``request_id`` and returning the SSE
        payload dict — the id has to be inside the payload (the client echoes
        it back on resolve), so the caller can't build the dict before we mint
        it, and we hand the built payload straight back so the caller never
        has to look it up again.
        """
        request_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_event_loop().create_future()
        )
        payload = payload_for(request_id)
        async with self._lock:
            self._items[(chat_id, request_id)] = PendingPrompt(
                event_type=self.event_type, payload=payload, future=future
            )
        return request_id, payload, future

    async def discard(self, chat_id: str, request_id: str) -> None:
        """Forget a prompt. Idempotent — used in the awaiting side's
        ``finally`` once the future has settled (or the caller bailed)."""
        async with self._lock:
            self._items.pop((chat_id, request_id), None)

    async def resolve(
        self, chat_id: str, request_id: str, result: dict[str, Any]
    ) -> bool:
        """Settle one prompt. Returns False when the id is unknown or the
        future already settled (idempotent — a double-click can't crash the
        route)."""
        async with self._lock:
            item = self._items.get((chat_id, request_id))
        if item is None or item.future.done():
            return False
        item.future.set_result(result)
        return True

    async def cancel_chat(self, chat_id: str, result: dict[str, Any]) -> None:
        """Settle every outstanding prompt for ``chat_id`` with ``result``.

        Called at turn end so a stranded future can never outlive the turn
        that owns it.
        """
        async with self._lock:
            stale = [k for k in self._items if k[0] == chat_id]
            for key in stale:
                item = self._items.pop(key, None)
                if item is not None and not item.future.done():
                    item.future.set_result(result)

    def snapshot(self, chat_id: str) -> list[PendingPrompt]:
        """Outstanding prompts for ``chat_id``, oldest first.

        Sync on purpose: the SSE attach path reads this while building its
        generator, and dict iteration is atomic enough here (insertion order
        is the emission order, and a concurrent insert only means the
        subscriber gets that prompt over the live queue instead).
        """
        return [
            item
            for (cid, _rid), item in self._items.items()
            if cid == chat_id and not item.future.done()
        ]


# Every PendingPrompts instance, in construction order. Small and fixed
# (two entries today) — a list keeps `snapshot_pending` trivial.
_REGISTRIES: list[PendingPrompts] = []


def snapshot_pending(chat_id: str) -> list[tuple[str, dict[str, Any]]]:
    """``[(event_type, payload), …]`` for everything ``chat_id`` is blocked on.

    The stream route replays these to each new subscriber so a reattaching
    client gets the permission / ask_user card back instead of staring at a
    turn that can never finish.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for reg in _REGISTRIES:
        for item in reg.snapshot(chat_id):
            out.append((item.event_type, item.payload))
    return out
