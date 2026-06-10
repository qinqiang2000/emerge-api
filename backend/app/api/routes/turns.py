"""Turn-as-resource HTTP routes (M11 Phase A T2).

Wires :mod:`app.chat.turn_registry` into FastAPI. A *turn* is now an
addressable resource the backend owns; the SSE stream is a subscription
that any number of clients can attach to / detach from / re-attach to
without affecting the running asyncio.Task.

Routes:

* ``POST /lab/chats/{cid}/turns``                — start a new turn.
* ``GET  /lab/chats/{cid}/turns/{tid}/stream``   — attach (with optional
                                                   ``after_offset`` for
                                                   replay-from-jsonl
                                                   bridging).
* ``POST /lab/chats/{cid}/turns/{tid}/cancel``   — idempotent cancel.
* ``GET  /lab/chats/{cid}/turn_state``           — "is there an active
                                                   turn for this chat,
                                                   and at what offset?"

A module-level :data:`_REGISTRY` keeps things simple. Tests can override
via the :func:`get_registry` dependency (FastAPI ``Depends``) if they
need a clean registry per case — the integration tests in this PR use
the module-level instance and rely on per-test ``chat_id`` isolation
plus turn-finishes-when-test-finishes semantics.

The route layer is responsible for replaying ``events.jsonl`` when:

* the cold-cache attach happens after the turn already finished and was
  evicted from the registry (``lookup_turn`` returns ``None``) — replay
  whatever the disk has, then close.
* the subscriber's ``after_offset`` is behind the live ``last_offset``
  — replay the bridge slice from disk, then subscribe live so we don't
  lose ordering. (TurnRegistry deliberately doesn't buffer; see
  `test_late_subscriber_misses_old_chunks` in T1.)

What we do NOT do:
* no file-watcher / tail-f on events.jsonl — the in-memory broadcast is
  the live source; jsonl is purely for replay of what already happened.
* no buffering inside the registry — the route layer's bridge handles
  the offset gap, and that's sufficient because the wrapper task
  appends to jsonl synchronously before fanning out to subscribers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.routes._safety import safe_chat_id
from app.api.routes.chat import SurfaceContext, _get_chat_service
from app.chat.log import _chat_log_path
from app.chat.turn_registry import (
    TurnAlreadyActiveError,
    TurnEntry,
    TurnRegistry,
    TurnStatus,
)
from app.config import get_settings


router = APIRouter(dependencies=[Depends(bind_workspace)])
_log = logging.getLogger(__name__)


# Module-level singleton. Acceptable for now per M11 plan §T2 — keeps the
# wiring simple. Future tests can use the :func:`get_registry` dependency
# to override (FastAPI's ``dependency_overrides`` mechanism). The
# integration tests in T2 deliberately use the real singleton and rely on
# per-test ``chat_id`` isolation.
_REGISTRY = TurnRegistry()


def get_registry() -> TurnRegistry:
    """FastAPI dependency. Returns the module-level singleton.

    Indirection so tests / future refactors can swap in a fresh instance
    via ``app.dependency_overrides[get_registry] = lambda: TurnRegistry()``
    without touching the route bodies.
    """
    return _REGISTRY


# ── request bodies ──────────────────────────────────────────────────────


class StartTurnBody(BaseModel):
    """Body for ``POST /lab/chats/{cid}/turns``.

    Carries the union of today's ``ChatBody`` and ``UnboundTurnBody`` so
    one route handles every flavour of turn (committed project,
    ``_chats`` unbound, ``p_unset`` legacy auto-mint):

    * ``slug`` is the folder-name handle for committed projects, the
      ``_chats`` sentinel for unbound chats, or ``p_unset`` for the
      legacy empty-hero auto-mint path.
    * ``user_message`` / ``attachments`` / ``surface_context`` mirror
      the existing chat envelope; ``ChatService.chat_turn`` keeps its
      pre-M11 signature.
    """

    slug: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None
    surface_context: SurfaceContext | None = None
    # "browser" (default) = frontend is active, rich UI cards render automatically.
    # "headless" = CLI agent / MCP client / programmatic caller; agent must emit
    # full text output instead of deferring to UI components.
    interface: str = "browser"


# ── helpers ─────────────────────────────────────────────────────────────


def _chunk_for_event(etype: str, payload: dict[str, Any]) -> str:
    """Render one persisted jsonl event back into the same SSE chunk
    shape ``ChatService.chat_turn`` yields. Used by :func:`replay_from_disk`.

    Matches :func:`app.chat.stream.sse_event` byte-for-byte so the route
    handler downstream can parse live + replay chunks identically.
    """
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {etype}\ndata: {data}\n\n"


def _split_sse_chunk(chunk: str) -> dict[str, str]:
    """Parse a ``event: x\ndata: y\n\n`` chunk into ``{event, data}``.

    ``sse_starlette.EventSourceResponse`` wants those two fields as plain
    strings, so we strip the SSE framing and hand them over for
    re-serialisation.
    """
    lines = chunk.strip().split("\n")
    event_line = next(
        (ln for ln in lines if ln.startswith("event:")), "event: message"
    )
    data_line = next(
        (ln for ln in lines if ln.startswith("data:")), "data: {}"
    )
    return {
        "event": event_line.split(":", 1)[1].strip(),
        "data": data_line.split(":", 1)[1].strip(),
    }


def _jsonl_line_count(path: Path) -> int:
    """Count non-empty lines in ``path``. Missing file → 0.

    Used by the cold-cache branch of the turn-state route so a reloading
    client sees a stable offset to hydrate from even after the turn has
    finished and been evicted from the registry.
    """
    if not path.exists():
        return 0
    try:
        # Read once, split — chat jsonl files are tiny (KBs), no need
        # for a streaming line counter.
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return sum(1 for ln in text.splitlines() if ln.strip())


def _resolve_log_path(workspace: Path, chat_id: str) -> Path:
    """Locate the events.jsonl for ``chat_id``, project-aware.

    A chat may live under ``<slug>/chats/<cid>.jsonl`` (committed
    project) or ``_chats/<cid>.jsonl`` (unbound). The route layer does
    not know which without scanning, so we mirror what
    :func:`app.chat.log._chat_log_path` does for the unbound case, then
    fall back to a search across project folders for the committed
    case.

    Order: prefer the unbound path if it exists; otherwise scan project
    folders for ``<slug>/chats/<cid>.jsonl``. Matches the resolver shape
    used by ``GET /lab/chats/{cid}/events`` (unbound) and
    ``GET /lab/chats/{slug}/{cid}`` (project) — except those branches
    take the slug from the URL. Here we don't have it, so we search.
    """
    # Unbound chat first — cheapest hit, deterministic path.
    unbound = _chat_log_path(workspace, "_chats", chat_id)
    if unbound.exists():
        return unbound

    # Project chat — scan ``<workspace>/<slug>/chats/<cid>.jsonl``.
    # Underscore-prefixed children are workspace-internal (``_chats``,
    # ``_staging``, ``_keys.json``…) so we skip them. The scan is O(#projects)
    # which is small (a handful for active labs); doing it in Python avoids
    # a separate pid_index lookup hop for the few routes that need this.
    if workspace.exists():
        for child in workspace.iterdir():
            if not child.is_dir() or child.name.startswith("_"):
                continue
            candidate = child / "chats" / f"{chat_id}.jsonl"
            if candidate.exists():
                return candidate

    # Default: unbound path (may not exist) — keeps callers from having
    # to handle ``None`` for an empty/new chat.
    return unbound


async def replay_from_disk(
    workspace: Path,
    chat_id: str,
    after: int,
    until: int | None = None,
) -> AsyncIterator[str]:
    """Replay events.jsonl as SSE chunks.

    Skips the first ``after`` lines (the client already has them); if
    ``until`` is set, stops *before* that line index (exclusive upper
    bound). Empty/missing log → empty iterator.

    Returns chunks in the same shape :func:`app.chat.stream.sse_event`
    produces, so the route handler doesn't have to special-case
    live-vs-replay downstream.
    """
    log_path = _resolve_log_path(workspace, chat_id)
    if not log_path.exists():
        return

    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                if idx < after:
                    continue
                if until is not None and idx >= until:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # Skip junk — replay degrades to whatever is parseable.
                    continue
                etype = event.pop("type", "message")
                yield _chunk_for_event(etype, event)
    except OSError as exc:
        _log.warning("replay_from_disk OSError on %s: %s", log_path, exc)
        return


# ── shared helpers ──────────────────────────────────────────────────────


async def _start_turn_for(
    *,
    cid: str,
    body: StartTurnBody,
    registry: TurnRegistry,
    tenant_key: str = "",
) -> TurnEntry:
    """Build the chat_turn runner factory + call ``registry.start``.

    Note: validation of ``cid`` (via :func:`safe_chat_id`) is the
    caller's responsibility — the route handler validates inline before
    calling.

    Raises :class:`HTTPException` 409 with the standard
    ``error_code: turn_already_active`` envelope when a turn is already
    running on the same chat.
    """
    svc = _get_chat_service()
    surface_dict = (
        body.surface_context.model_dump() if body.surface_context else None
    )

    def factory() -> AsyncIterator[str]:
        # ``runner_factory`` is zero-arg so the registry can construct
        # the iterator inside the wrapper task. A fresh call each turn —
        # callers don't reuse this factory.
        return svc.chat_turn(
            slug=body.slug,
            chat_id=cid,
            user_message=body.user_message,
            attachments=body.attachments,
            surface_context=surface_dict,
            interface=body.interface,
        )

    try:
        return await registry.start(
            chat_id=cid,
            slug=body.slug,
            runner_factory=factory,
            tenant_key=tenant_key,
        )
    except TurnAlreadyActiveError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "turn_already_active",
                "error_message_en": str(exc),
                "active_turn_id": exc.active_turn_id,
            },
        ) from exc


def _attach_and_stream(
    *,
    cid: str,
    tid: str,
    after_offset: int,
    registry: TurnRegistry,
) -> EventSourceResponse:
    """Attach to a turn's broadcast and return an ``EventSourceResponse``.

    Validation of ``cid`` is the caller's responsibility (same rationale
    as :func:`_start_turn_for`).

    Cold cache (no entry) → replay whatever ``events.jsonl`` has from
    ``after_offset`` and close.
    Hot cache, behind live offset → replay the bridge slice from disk,
    then subscribe.
    Hot cache, caught up → subscribe directly.
    """
    workspace = current_ws()
    entry = registry.lookup_turn(tid)

    # Short-circuit reattaches to an already-finished turn. Two paths land
    # here:
    #   (a) Cold cache — registry has no entry for ``tid`` (evicted or
    #       bogus). ``replay_from_disk`` may yield zero chunks (e.g.
    #       ``after_offset`` past the jsonl tail) and the empty
    #       generator below trips sse_starlette into a 503 fallback.
    #   (b) Hot cache, terminal status, caller already at the tail
    #       (``after_offset >= entry.last_offset``) — bridge replay is
    #       empty and ``subscribe`` returns a queue whose only item is
    #       the ``None`` sentinel; again zero yielded chunks → 503.
    # Yielding a synthetic ``turn_end`` event in both cases gives:
    #   1. a clean HTTP 200 SSE response (sse_starlette commits the
    #      status line as soon as the generator yields anything),
    #   2. an explicit "this turn is over" signal so the client can flip
    #      its inflight state without waiting on jsonl hydrate or a
    #      separate ``turn_state`` round-trip,
    #   3. no impact on the live-stream / hot-cache / offset-bridge
    #      paths — those still emit real events and the real
    #      ``turn_end`` from the runner.
    _is_terminal_reattach = (
        entry is None
        or (
            entry.status != TurnStatus.RUNNING
            and after_offset >= entry.last_offset
        )
    )

    async def gen() -> AsyncIterator[dict[str, str]]:
        if entry is None:
            # Cold cache — replay whatever disk has, then close. We
            # still emit the synthetic ``turn_end`` below so the
            # response is a clean 200 even when the jsonl is empty.
            async for chunk in replay_from_disk(workspace, cid, after_offset):
                yield _split_sse_chunk(chunk)
            yield _split_sse_chunk(_chunk_for_event("turn_end", {}))
            return

        if _is_terminal_reattach:
            # Hot cache but the turn already finished AND the caller is
            # already at the tail. Skip subscribe (would only yield the
            # sentinel) and emit the synthetic close so the response is
            # 200 + a usable "turn over" signal.
            yield _split_sse_chunk(_chunk_for_event("turn_end", {}))
            return

        # Hot cache: bridge any offset gap from disk so the live
        # subscription picks up at the right place.
        if after_offset < entry.last_offset:
            async for chunk in replay_from_disk(
                workspace, cid, after_offset, until=entry.last_offset,
            ):
                yield _split_sse_chunk(chunk)

        sub_entry, queue = await registry.subscribe(tid)
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield _split_sse_chunk(chunk)
        finally:
            registry.unsubscribe(sub_entry, queue)

    return EventSourceResponse(gen())


# ── routes ──────────────────────────────────────────────────────────────


@router.post("/lab/chats/{cid}/turns")
async def start_turn(
    cid: str,
    body: StartTurnBody,
    registry: TurnRegistry = Depends(get_registry),
) -> dict[str, str]:
    """Kick off a new chat turn for ``cid``.

    Returns ``{turn_id, status}``. The turn keeps running independently
    of this HTTP request — the client attaches with ``GET .../stream``
    once it has the ``turn_id``.

    Rejects with HTTP 409 / ``error_code: turn_already_active`` if a
    turn is currently running on the same chat (one-per-chat semantics
    inherited from the registry).
    """
    safe_chat_id(cid)
    # Tag the turn with the caller's team workspace so the "active" lookups
    # (spine / popover dots) never cross-light another team's same-named slug.
    entry = await _start_turn_for(
        cid=cid, body=body, registry=registry, tenant_key=str(current_ws()),
    )
    return {"turn_id": entry.turn_id, "status": entry.status.value}


@router.get("/lab/chats/{cid}/turns/{tid}/stream")
async def stream_turn(
    cid: str,
    tid: str,
    after_offset: int = 0,
    registry: TurnRegistry = Depends(get_registry),
) -> EventSourceResponse:
    """Subscribe to a turn's SSE stream.

    ``after_offset`` is the client's last-known event-line index in
    ``events.jsonl``. The route bridges that offset to the live broadcast
    by:

    * cold cache (``lookup_turn`` returns ``None``) → the turn already
      finished and was evicted, OR the ``turn_id`` is bogus. Replay
      whatever ``events.jsonl`` has from ``after_offset`` and close.
    * hot cache, behind live offset → replay the missed bridge slice
      ``[after_offset, entry.last_offset)`` from disk, then subscribe
      and stream live chunks.
    * hot cache, caught up → subscribe directly.

    On terminal status the wrapper task puts a single ``None`` sentinel
    on every subscriber queue, which we translate into an EOF for the
    SSE stream (sse_starlette closes the connection when the generator
    returns).
    """
    safe_chat_id(cid)
    return _attach_and_stream(
        cid=cid, tid=tid, after_offset=after_offset, registry=registry,
    )


@router.post("/lab/chats/{cid}/turns/{tid}/cancel")
async def cancel_turn(
    cid: str,
    tid: str,
    registry: TurnRegistry = Depends(get_registry),
) -> dict[str, str]:
    """Cancel a running turn. Idempotent.

    * Unknown ``tid`` → ``{status: 'not_found'}`` (still HTTP 200 — the
      client doesn't need to differentiate "I cancelled" from "it was
      already gone").
    * Known ``tid`` → ``{status: <current status>}`` after invoking
      ``registry.cancel``. For an in-flight turn the status will be
      ``cancelled`` by the time the wrapper task settles; for an
      already-terminal turn we report its current status verbatim.
    """
    safe_chat_id(cid)
    entry = registry.lookup_turn(tid)
    if entry is None:
        return {"status": "not_found"}

    await registry.cancel(tid)
    # ``cancel`` returns immediately after ``task.cancel()``; the wrapper
    # task may need an event-loop tick to flip status. The HTTP contract
    # is "we requested cancel" — the subscriber receives the sentinel
    # asynchronously and the next ``turn_state`` read shows the final
    # status. Echoing ``entry.status`` here gives the client whatever
    # value is current at response time (typically ``cancelled`` for an
    # in-flight turn, the existing terminal state for a finished one).
    return {"status": entry.status.value}


@router.get("/lab/chats/{cid}/turn_state")
async def turn_state(
    cid: str,
    registry: TurnRegistry = Depends(get_registry),
) -> dict[str, Any]:
    """Snapshot of the chat's live turn (if any) plus a hydrate offset.

    * Active turn for ``cid`` → ``{active_turn_id, status, last_offset}``.
    * No active turn → ``{active_turn_id: null, status: null,
      last_offset: <events.jsonl line count>}``. The line count lets a
      cold-reloading client know "I've seen N events; hydrate from
      there" without first attaching to a stream.

    Why we don't return finished-but-not-evicted turns: the route uses
    :meth:`TurnRegistry.get_active_for_chat`, which intentionally
    filters out terminal entries. A client that just finished tailing
    a turn will see its status as ``done``/etc on the final
    ``turn_end`` event already; reading ``turn_state`` then should
    report "no live turn" and let the client re-hydrate from jsonl.
    """
    safe_chat_id(cid)
    entry = registry.get_active_for_chat(cid)
    if entry is not None:
        return {
            "active_turn_id": entry.turn_id,
            "status": entry.status.value,
            "last_offset": entry.last_offset,
        }

    workspace = current_ws()
    log_path = _resolve_log_path(workspace, cid)
    return {
        "active_turn_id": None,
        "status": None,
        "last_offset": _jsonl_line_count(log_path),
    }
