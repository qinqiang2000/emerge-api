"""ContextVar bridge from the chat-turn loop to MCP tools that want to push
SSE events back to the active client.

The chat service sets `current_sse_writer` at the top of `chat_turn` and
clears it in a `finally`. UI-action tools (`ui_goto_page`, etc.) read it via
`current_sse_writer.get()` and use the callable to emit an `event: ui_action`
frame on the still-open SSE stream. Anything outside an active chat turn
(e.g. the public `/v1/extract` fast-path) sees the `None` sentinel and the
tool errors out cleanly — UI-action tools are session-bound by construction.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

# Signature mirrors `sse_event(event_type, payload)` — the tool passes the
# already-assembled dict payload and the writer takes care of wrapping it
# into the SSE frame and yielding it onto the chat-turn generator.
SSEWriter = Callable[[str, dict[str, Any]], Awaitable[None]]

current_sse_writer: ContextVar[SSEWriter | None] = ContextVar(
    "current_sse_writer", default=None,
)
