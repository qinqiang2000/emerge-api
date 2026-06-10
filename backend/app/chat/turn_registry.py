"""In-memory registry of live chat turns.

Per M11 plan (`docs/superpowers/plans/2026-05-19-turn-as-resource.md`), a
chat *turn* is decoupled from the HTTP request that kicked it off. The
TurnRegistry owns the running asyncio.Task and lets any number of HTTP
clients attach to / detach from the live event stream without affecting
the turn itself.

Contract highlights:

* **One active turn per chat_id.** Calling :meth:`TurnRegistry.start`
  while a turn is already running on the same chat raises
  :class:`TurnAlreadyActiveError`. When the running turn reaches any
  terminal status (``done`` / ``cancelled`` / ``error``) the chat is
  free again.
* **Multi-subscriber broadcast.** Each :meth:`subscribe` call hands back
  a fresh ``asyncio.Queue``. The wrapped runner pulls chunks one at a
  time and fans them out via ``put_nowait`` to every queue that exists
  at the moment of fan-out.
* **Late subscribers do NOT see replay.** The registry deliberately
  keeps zero history: a subscriber that joins after the first ``N``
  chunks have already been emitted will only receive chunk ``N+1``
  onwards. Replaying the missed window is the route layer's job — it
  reads ``events.jsonl`` for that. ``last_offset`` is published so the
  route layer can decide what slice to replay before subscribing.
* **Sentinel on terminal status.** When a turn finishes (regardless of
  status) every current subscriber queue receives a single ``None``
  value. Consumers loop ``while True: chunk = await q.get(); if chunk
  is None: break; yield chunk``.
* **Idempotent cancel.** ``cancel(turn_id)`` on an unknown or already
  finished turn is a no-op (no exception). Internally it does
  ``task.cancel()``; the wrapper catches ``CancelledError`` and flips
  status to ``cancelled``.
* **Runner exceptions are captured.** Any exception raised by the
  runner becomes ``status='error'`` and ``entry.error`` is populated
  with the project-wide ``{error_code, error_message_en}`` envelope.

The registry is pure asyncio + dataclasses — no FastAPI imports. This
keeps it trivially unit-testable.  It is also process-local: a backend
restart loses every entry. ``events.jsonl`` is the durable record (per
CLAUDE.md "events.jsonl remains source of truth").
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from enum import Enum


__all__ = [
    "TurnAlreadyActiveError",
    "TurnEntry",
    "TurnRegistry",
    "TurnStatus",
]


class TurnStatus(str, Enum):
    """Lifecycle states for a single turn.

    ``str`` mix-in so equality with plain strings (``entry.status ==
    "running"``) keeps working for the route layer / tests, while the
    enum gives us a single place to enumerate the valid values.
    """

    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


_TERMINAL_STATUSES = frozenset(
    {TurnStatus.DONE, TurnStatus.CANCELLED, TurnStatus.ERROR}
)


class TurnAlreadyActiveError(RuntimeError):
    """Raised when :meth:`TurnRegistry.start` is called for a chat that
    already has a turn in flight."""

    def __init__(self, chat_id: str, active_turn_id: str) -> None:
        super().__init__(
            f"chat '{chat_id}' already has an active turn "
            f"'{active_turn_id}'"
        )
        self.chat_id = chat_id
        self.active_turn_id = active_turn_id


@dataclass
class TurnEntry:
    """Operational state for one in-flight or recently-finished turn.

    Fields here are kept narrow on purpose: anything the route layer
    needs that isn't in ``events.jsonl`` lives in this dataclass; nothing
    here is durable across a backend restart.

    ``task`` is ``None`` only during the brief window inside
    :meth:`TurnRegistry.start` between dataclass construction and task
    spawn — every value the registry hands out has it set.
    """

    turn_id: str
    chat_id: str
    slug: str
    # Opaque tenant discriminator (the team's workspace path string). The
    # registry is process-global and ``slug`` collides across teams (two teams
    # can both own a project named "invoices"), so the "active" lookups filter
    # on this to keep one team's live turns from lighting up another team's UI.
    # Empty string = the open-mode single workspace.
    tenant_key: str = ""
    task: asyncio.Task[None] | None = None
    status: TurnStatus = TurnStatus.RUNNING
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    last_offset: int = 0
    error: dict[str, str] | None = None
    subscribers: set[asyncio.Queue[str | None]] = field(default_factory=set)


class TurnRegistry:
    """In-memory map of ``chat_id`` ↔ ``TurnEntry``.

    One active turn per ``chat_id``; ``start()`` rejects concurrent
    starts via an asyncio.Lock so the "is there an active turn" check
    and the insert happen atomically. Live subscribers get a per-call
    queue; the wrapper task fans incoming chunks out and posts a single
    ``None`` sentinel when the turn ends.

    Note: the registry does **not** evict finished turns automatically.
    The route layer keeps a handle by ``turn_id`` so reattach within
    the same backend process can still resolve status / last_offset
    after a turn is done. A future task (out of M11 scope) may add a
    TTL-based cleanup.
    """

    def __init__(self) -> None:
        self._by_chat: dict[str, TurnEntry] = {}
        self._by_turn: dict[str, TurnEntry] = {}
        self._lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(
        self,
        *,
        chat_id: str,
        slug: str,
        runner_factory: Callable[[], AsyncIterator[str]],
        tenant_key: str = "",
    ) -> TurnEntry:
        """Spawn a fresh turn for ``chat_id``.

        ``runner_factory`` is a zero-arg callable returning a fresh
        ``AsyncIterator[str]`` — this lets the registry construct the
        iterator inside the worker task so a cancel hits the runner
        body, not just the caller's setup code.

        Raises :class:`TurnAlreadyActiveError` if a turn is currently
        running on the same chat (the chat is "free" once the current
        turn reaches any terminal status).
        """
        async with self._lock:
            existing = self._by_chat.get(chat_id)
            if existing is not None and existing.status == TurnStatus.RUNNING:
                raise TurnAlreadyActiveError(chat_id, existing.turn_id)

            turn_id = uuid.uuid4().hex[:12]
            # Build the entry up-front (sans task) so the wrapper can
            # close over the same instance the registry hands back.
            entry = TurnEntry(
                turn_id=turn_id, chat_id=chat_id, slug=slug, tenant_key=tenant_key
            )
            loop = asyncio.get_event_loop()
            entry.task = loop.create_task(
                _run_turn(entry, runner_factory),
                name=f"turn-{turn_id}",
            )

            self._by_chat[chat_id] = entry
            self._by_turn[turn_id] = entry
            return entry

    async def cancel(self, turn_id: str) -> None:
        """Cancel a running turn. Idempotent.

        Unknown ``turn_id`` is a silent no-op; an already-finished turn
        is also a no-op. The wrapper task catches ``CancelledError`` and
        sets status to ``cancelled``; subscribers receive the sentinel
        in the wrapper's ``finally`` block.
        """
        entry = self._by_turn.get(turn_id)
        if entry is None:
            return
        if entry.status in _TERMINAL_STATUSES:
            return
        if entry.task is None:
            return
        entry.task.cancel()

    # ── subscriptions ────────────────────────────────────────────────

    async def subscribe(
        self, turn_id: str
    ) -> tuple[TurnEntry, asyncio.Queue[str | None]]:
        """Register a new subscriber queue for ``turn_id``.

        Returns ``(entry, queue)``. The queue receives every chunk
        produced from this point forward, then a single ``None``
        sentinel when the turn ends. Late subscribers do NOT replay
        old chunks (the route layer handles replay against
        ``events.jsonl``).

        If the turn has already reached a terminal status, the
        subscriber gets only the sentinel — callers should still drain
        in their normal loop and check ``entry.status`` for the final
        outcome.
        """
        entry = self._by_turn.get(turn_id)
        if entry is None:
            raise KeyError(f"unknown turn_id '{turn_id}'")

        queue: asyncio.Queue[str | None] = asyncio.Queue()
        if entry.status in _TERMINAL_STATUSES:
            # Already done — give the subscriber an immediate sentinel
            # so the standard drain loop terminates without special
            # casing.
            queue.put_nowait(None)
        else:
            entry.subscribers.add(queue)
        return entry, queue

    def unsubscribe(
        self, entry: TurnEntry, q: asyncio.Queue[str | None]
    ) -> None:
        """Remove ``q`` from ``entry``'s subscriber set. Idempotent."""
        entry.subscribers.discard(q)

    # ── lookups ──────────────────────────────────────────────────────

    def get_active_for_chat(self, chat_id: str) -> TurnEntry | None:
        """Return the currently-running entry for ``chat_id``, if any.

        Finished entries are still indexed in ``_by_turn`` for reattach;
        this lookup specifically asks "is there a *live* turn for this
        chat" so the route layer doesn't false-positive on a turn that
        just finished.
        """
        entry = self._by_chat.get(chat_id)
        if entry is None:
            return None
        if entry.status != TurnStatus.RUNNING:
            return None
        return entry

    def lookup_turn(self, turn_id: str) -> TurnEntry | None:
        """Return any entry by ``turn_id``, live or finished."""
        return self._by_turn.get(turn_id)

    def active_chat_ids(self, tenant_key: str | None = None) -> set[str]:
        """``chat_id`` set with a *live* turn right now.

        Powers the "still running" markers the FE paints on chat-history
        rows you've navigated away from — the turn keeps running after the
        SSE detaches, so the UI needs an authoritative liveness probe that
        isn't the (single-slice) FE ``busy`` flag. Finished entries linger
        in ``_by_chat`` until the next start on the same chat replaces them,
        but their status isn't RUNNING so they're filtered out here.

        ``tenant_key`` (``None`` = no filter) scopes the result to one team's
        workspace. ``chat_id`` is globally unique so cross-team leakage is
        already impossible here, but filtering keeps the contract symmetric
        with :meth:`active_slugs` (defence in depth).
        """
        return {
            cid
            for cid, e in self._by_chat.items()
            if e.status == TurnStatus.RUNNING
            and (tenant_key is None or e.tenant_key == tenant_key)
        }

    def active_slugs(self, tenant_key: str | None = None) -> set[str]:
        """Project ``slug`` set with at least one live turn right now.

        Cross-project peer of :meth:`active_chat_ids` — lets the spine paint
        a "working" dot on a project row whose chat is mid-turn while the
        user is looking at a *different* project. Unbound turns carry the
        ``_chats`` sentinel slug, which matches no real project, so they're
        naturally excluded.

        ``tenant_key`` (``None`` = no filter) MUST be passed in tenant mode:
        project ``slug`` collides across teams, so an unscoped lookup would
        light up another team's project row.
        """
        return {
            e.slug
            for e in self._by_chat.values()
            if e.status == TurnStatus.RUNNING
            and (tenant_key is None or e.tenant_key == tenant_key)
        }


# ── internals ────────────────────────────────────────────────────────


async def _run_turn(
    entry: TurnEntry,
    runner_factory: Callable[[], AsyncIterator[str]],
) -> None:
    """Wrap the runner so we can fan out chunks + capture terminal state.

    Lives at module scope (not nested inside :meth:`TurnRegistry.start`)
    so the asyncio.Task name shows ``turn-<id>`` rather than the closure
    name in tracebacks.
    """
    # ``runner_factory()`` MUST be inside the try: it executes user/service
    # code (``ChatService.chat_turn(...)``) and can raise synchronously —
    # e.g. a TypeError on signature mismatch. If it raised outside the try,
    # the task would die with ``entry.status`` stuck at RUNNING and the
    # sentinel never broadcast: every subscriber blocks on ``queue.get()``
    # forever and the chat is wedged behind 409 ``turn_already_active``
    # until restart. (Root cause of the 2026-06-10 turns-SSE test deadlock.)
    runner: AsyncIterator[str] | None = None
    try:
        runner = runner_factory()
        async for chunk in runner:
            entry.last_offset += 1
            # Snapshot subscribers before iterating; the set may be
            # mutated by ``unsubscribe`` while we're broadcasting.
            for q in list(entry.subscribers):
                q.put_nowait(chunk)
        entry.status = TurnStatus.DONE
    except asyncio.CancelledError:
        entry.status = TurnStatus.CANCELLED
        # Don't re-raise: we want the Task to complete cleanly so
        # ``await entry.task`` in tests / route layer doesn't propagate
        # the cancellation. The wrapper's whole purpose is to absorb
        # cancellation and translate it into a status flip + sentinel.
    except Exception as exc:  # noqa: BLE001 — capture every failure mode
        entry.status = TurnStatus.ERROR
        entry.error = {
            "error_code": "turn_failed",
            "error_message_en": str(exc),
        }
    finally:
        entry.finished_at = time.time()
        # Drain the underlying iterator's resources if it supports it
        # (async generators expose ``aclose``). ``runner`` is None when
        # the factory itself raised.
        aclose = getattr(runner, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except BaseException:  # noqa: BLE001
                pass
        for q in list(entry.subscribers):
            q.put_nowait(None)
