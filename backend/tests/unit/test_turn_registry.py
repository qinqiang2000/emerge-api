"""Unit coverage for :mod:`app.chat.turn_registry`.

Six cases mandated by the M11 plan §Phase A T1
(`docs/superpowers/plans/2026-05-19-turn-as-resource.md`).

Each test drives the registry with a tiny ``async def`` generator
runner; no FastAPI / HTTP machinery is involved here.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.chat.turn_registry import (
    TurnAlreadyActiveError,
    TurnRegistry,
    TurnStatus,
)


# ── helpers ──────────────────────────────────────────────────────────


def _yielding(chunks: list[str]):
    """Build a zero-arg ``runner_factory`` that emits the given chunks."""

    async def _gen() -> AsyncIterator[str]:
        for c in chunks:
            yield c
            # Cooperative yield so subscriber drainers can interleave.
            await asyncio.sleep(0)

    def factory() -> AsyncIterator[str]:
        return _gen()

    return factory


async def _drain(q: asyncio.Queue[str | None]) -> list[str]:
    """Pull from ``q`` until the registry's None sentinel arrives."""
    out: list[str] = []
    while True:
        chunk = await q.get()
        if chunk is None:
            return out
        out.append(chunk)


# ── tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_and_subscribe_basic() -> None:
    """Smoke: 3-chunk runner → subscriber sees all 3 + sentinel; status done."""
    reg = TurnRegistry()
    entry = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=_yielding(["a", "b", "c"]),
    )
    _, q = await reg.subscribe(entry.turn_id)

    received = await _drain(q)

    assert received == ["a", "b", "c"]
    assert entry.status == TurnStatus.DONE
    assert entry.last_offset == 3
    assert entry.error is None
    assert entry.task is not None
    await entry.task  # ensure the wrapper task has fully unwound


@pytest.mark.asyncio
async def test_two_subscribers_get_same_stream() -> None:
    """Both subscribers, registered before the runner starts streaming,
    must see the full chunk list."""
    reg = TurnRegistry()
    entry = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=_yielding(["x", "y", "z"]),
    )
    _, q1 = await reg.subscribe(entry.turn_id)
    _, q2 = await reg.subscribe(entry.turn_id)

    a, b = await asyncio.gather(_drain(q1), _drain(q2))

    assert a == ["x", "y", "z"]
    assert b == ["x", "y", "z"]
    assert entry.status == TurnStatus.DONE


@pytest.mark.asyncio
async def test_late_subscriber_misses_old_chunks() -> None:
    """Locks in the documented contract: the registry does not buffer
    chunks for late subscribers. They see only chunks emitted after
    they attached. Replaying the missed window is the route layer's
    job, against events.jsonl."""
    reg = TurnRegistry()
    # ``gate`` lets the test pause the runner between chunks 2 and 3
    # so we can subscribe in the middle of the stream deterministically.
    gate = asyncio.Event()
    seen_two = asyncio.Event()

    async def _gen() -> AsyncIterator[str]:
        yield "1"
        yield "2"
        seen_two.set()
        await gate.wait()
        yield "3"
        yield "4"

    entry = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=lambda: _gen(),
    )

    # Subscribe an early follower so the runner has at least one queue
    # to fan out into (without it, ``put_nowait`` is a no-op and the
    # offset would still advance, but we want to mirror the real flow).
    _, early = await reg.subscribe(entry.turn_id)

    early_pull: list[str] = []
    # Pump the first two chunks into ``early`` so the runner reaches
    # the gate.
    early_pull.append(await early.get())  # "1"
    early_pull.append(await early.get())  # "2"
    await seen_two.wait()
    assert entry.last_offset == 2

    # Now attach the late subscriber and let the runner continue.
    _, late = await reg.subscribe(entry.turn_id)
    gate.set()

    late_chunks = await _drain(late)
    early_pull.extend(await _drain(early))

    assert late_chunks == ["3", "4"], "late subscriber must NOT see old chunks"
    assert early_pull == ["1", "2", "3", "4"]
    assert entry.status == TurnStatus.DONE


@pytest.mark.asyncio
async def test_cancel_propagates() -> None:
    """Runner yields once then awaits forever; ``cancel`` flips status to
    cancelled and subscribers receive the sentinel."""
    reg = TurnRegistry()
    started = asyncio.Event()

    async def _gen() -> AsyncIterator[str]:
        yield "hello"
        started.set()
        # Park indefinitely until cancelled.
        await asyncio.Event().wait()
        yield "never"

    entry = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=lambda: _gen(),
    )
    _, q = await reg.subscribe(entry.turn_id)

    first = await q.get()
    assert first == "hello"
    await started.wait()

    await reg.cancel(entry.turn_id)

    # The next item we read must be the None sentinel — no further data.
    sentinel = await q.get()
    assert sentinel is None
    assert entry.status == TurnStatus.CANCELLED
    assert entry.task is not None
    await entry.task  # wrapper absorbed CancelledError, so this is clean


@pytest.mark.asyncio
async def test_one_turn_per_chat() -> None:
    """Second ``start`` on the same chat while a turn is live raises;
    after the first turn finishes, a new start succeeds."""
    reg = TurnRegistry()

    gate = asyncio.Event()

    async def _gen() -> AsyncIterator[str]:
        yield "a"
        await gate.wait()

    entry1 = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=lambda: _gen(),
    )

    with pytest.raises(TurnAlreadyActiveError) as excinfo:
        await reg.start(
            chat_id="c1",
            slug="p_demo",
            runner_factory=_yielding(["nope"]),
        )
    assert excinfo.value.chat_id == "c1"
    assert excinfo.value.active_turn_id == entry1.turn_id

    # Let the first turn finish.
    gate.set()
    assert entry1.task is not None
    await entry1.task
    assert entry1.status == TurnStatus.DONE

    # Now a new start on the same chat must succeed.
    entry2 = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=_yielding(["b"]),
    )
    assert entry2.turn_id != entry1.turn_id
    _, q = await reg.subscribe(entry2.turn_id)
    assert await _drain(q) == ["b"]
    assert entry2.status == TurnStatus.DONE


@pytest.mark.asyncio
async def test_runner_exception() -> None:
    """Runner raising ``RuntimeError`` → status flips to error and
    ``entry.error`` carries the standard envelope; subscriber still gets
    the sentinel."""
    reg = TurnRegistry()

    async def _gen() -> AsyncIterator[str]:
        yield "ok"
        raise RuntimeError("boom")

    entry = await reg.start(
        chat_id="c1",
        slug="p_demo",
        runner_factory=lambda: _gen(),
    )
    _, q = await reg.subscribe(entry.turn_id)

    received = await _drain(q)

    assert received == ["ok"]
    assert entry.status == TurnStatus.ERROR
    assert entry.error == {
        "error_code": "turn_failed",
        "error_message_en": "boom",
    }
    assert entry.task is not None
    await entry.task  # exception was absorbed by the wrapper


@pytest.mark.asyncio
async def test_active_lookups_track_running_then_clear() -> None:
    """`active_chat_ids` / `active_slugs` report only live turns, and drop a
    turn the instant it finishes. These power the FE "still working" dots on
    chats / projects you've navigated away from — a finished turn that lingers
    in the registry (for reattach) must NOT keep its dot lit."""
    reg = TurnRegistry()
    gate = asyncio.Event()

    async def _gen() -> AsyncIterator[str]:
        yield "1"
        await gate.wait()

    entry = await reg.start(chat_id="c1", slug="proj-a", runner_factory=lambda: _gen())
    _, q = await reg.subscribe(entry.turn_id)
    assert (await q.get()) == "1"  # runner now parked on the gate → RUNNING

    # While running, both lookups see this chat / slug.
    assert reg.active_chat_ids() == {"c1"}
    assert reg.active_slugs() == {"proj-a"}

    # Release the gate → turn finishes; lookups go empty even though the
    # entry is still indexed for reattach.
    gate.set()
    assert (await q.get()) is None  # sentinel
    assert entry.task is not None
    await entry.task
    assert reg.active_chat_ids() == set()
    assert reg.active_slugs() == set()
    assert reg.lookup_turn(entry.turn_id) is not None  # still indexed


@pytest.mark.asyncio
async def test_active_lookups_scope_by_tenant() -> None:
    """Two teams own a same-named slug ("invoices"); a live turn in team A
    must NOT light up team B's project row. The slug-based lookup is scoped
    by ``tenant_key`` (the team's workspace path) to enforce isolation."""
    reg = TurnRegistry()
    gate = asyncio.Event()

    async def _park() -> AsyncIterator[str]:
        yield "x"
        await gate.wait()

    a = await reg.start(
        chat_id="c_a", slug="invoices", tenant_key="/ws/team-a",
        runner_factory=lambda: _park(),
    )
    b = await reg.start(
        chat_id="c_b", slug="invoices", tenant_key="/ws/team-b",
        runner_factory=lambda: _park(),
    )
    _, qa = await reg.subscribe(a.turn_id)
    _, qb = await reg.subscribe(b.turn_id)
    assert (await qa.get()) == "x"
    assert (await qb.get()) == "x"

    # Same slug across tenants, but each lookup sees only its own team.
    assert reg.active_slugs("/ws/team-a") == {"invoices"}
    assert reg.active_slugs("/ws/team-b") == {"invoices"}
    assert reg.active_chat_ids("/ws/team-a") == {"c_a"}
    assert reg.active_chat_ids("/ws/team-b") == {"c_b"}
    # No filter → both (used by tests / open mode).
    assert reg.active_chat_ids() == {"c_a", "c_b"}

    gate.set()
    assert (await qa.get()) is None
    assert (await qb.get()) is None
    assert a.task is not None and b.task is not None
    await a.task
    await b.task
