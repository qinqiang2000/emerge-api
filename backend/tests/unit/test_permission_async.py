"""Async coverage for the workspace permission gate's ask/approve round-trip."""
import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from app.chat.permissions import (
    cancel_pending,
    is_always_allowed,
    make_gate,
    request_permission,
    resolve_permission,
)


# Reuse the conftest `workspace` fixture.


@pytest.mark.asyncio
async def test_request_permission_approve(workspace: Path) -> None:
    events: list[tuple[str, dict]] = []

    async def writer(etype: str, payload: dict) -> None:
        events.append((etype, payload))
        # Resolve the future as soon as the SSE event lands — simulates the
        # frontend POSTing the approve decision back.
        await resolve_permission(
            chat_id="cX",
            request_id=payload["request_id"],
            decision="approve",
            scope="once",
        )

    result = await request_permission(
        chat_id="cX",
        tool_name="Bash",
        tool_input={"command": "curl https://example.com"},
        reason="network op",
        sse_writer=writer,
    )
    assert isinstance(result, PermissionResultAllow)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "permission_request"
    assert payload["tool_name"] == "Bash"
    assert payload["reason"] == "network op"
    assert "request_id" in payload


@pytest.mark.asyncio
async def test_request_permission_deny_with_message(workspace: Path) -> None:
    async def writer(etype: str, payload: dict) -> None:
        await resolve_permission(
            chat_id="cY",
            request_id=payload["request_id"],
            decision="deny",
            message="no thanks",
        )

    result = await request_permission(
        chat_id="cY",
        tool_name="WebFetch",
        tool_input={"url": "https://example.com"},
        reason="webfetch",
        sse_writer=writer,
    )
    assert isinstance(result, PermissionResultDeny)
    assert "no thanks" in result.message


@pytest.mark.asyncio
async def test_request_permission_no_writer_denies(workspace: Path) -> None:
    """No SSE writer attached (e.g. called outside a chat turn) → deny."""
    result = await request_permission(
        chat_id="cZ",
        tool_name="Bash",
        tool_input={"command": "curl https://example.com"},
        reason="x",
        sse_writer=None,
    )
    assert isinstance(result, PermissionResultDeny)


@pytest.mark.asyncio
async def test_resolve_unknown_request_returns_false() -> None:
    ok = await resolve_permission(
        chat_id="missing",
        request_id="missing",
        decision="approve",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_always_scope_marks_chat(workspace: Path) -> None:
    async def writer(etype: str, payload: dict) -> None:
        await resolve_permission(
            chat_id="cA",
            request_id=payload["request_id"],
            decision="approve",
            scope="always",
        )

    result = await request_permission(
        chat_id="cA",
        tool_name="WebFetch",
        tool_input={"url": "https://x"},
        reason="r",
        sse_writer=writer,
    )
    assert isinstance(result, PermissionResultAllow)
    assert is_always_allowed("cA", "WebFetch")
    assert not is_always_allowed("cB", "WebFetch")


@pytest.mark.asyncio
async def test_gate_short_circuits_on_always_allow(workspace: Path) -> None:
    # First call asks-and-approves with always scope; second call must
    # auto-allow without emitting another permission_request.
    events: list[tuple[str, dict]] = []

    async def writer(etype: str, payload: dict) -> None:
        events.append((etype, payload))
        await resolve_permission(
            chat_id="cG",
            request_id=payload["request_id"],
            decision="approve",
            scope="always",
        )

    gate = make_gate(workspace, chat_id="cG", sse_writer_getter=lambda: writer)
    r1 = await gate("WebFetch", {"url": "https://x"}, None)
    r2 = await gate("WebFetch", {"url": "https://y"}, None)
    assert isinstance(r1, PermissionResultAllow)
    assert isinstance(r2, PermissionResultAllow)
    assert len(events) == 1  # only the first call asked


@pytest.mark.asyncio
async def test_cancel_pending_resolves_dangling_futures(workspace: Path) -> None:
    """A chat that ends mid-ask must drop its outstanding futures."""
    captured: list[dict] = []

    async def writer(etype: str, payload: dict) -> None:
        captured.append(payload)
        # Deliberately do not resolve — we want to test that cancel_pending
        # cleans up the dangling future.

    task = asyncio.create_task(
        request_permission(
            chat_id="cCancel",
            tool_name="WebFetch",
            tool_input={"url": "https://x"},
            reason="r",
            sse_writer=writer,
        )
    )
    # Yield so the SSE writer runs and captures the request_id.
    for _ in range(5):
        if captured:
            break
        await asyncio.sleep(0.01)
    assert captured, "writer should have fired before we cancel"

    await cancel_pending("cCancel")
    result = await asyncio.wait_for(task, timeout=0.5)
    assert isinstance(result, PermissionResultDeny)
