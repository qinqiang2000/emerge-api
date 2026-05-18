"""Async user-question round-trip for the ``ask_user`` MCP tool.

This mirrors the structure of ``permissions.request_permission`` — same
``_pending`` futures registry, same chat-id-scoped cleanup — but the semantics
are different: ``ask_user`` is **not** a permission gate, it is a structured
question with user-chosen answers. The tool body in ``app/tools/ask_user.py``
emits an SSE ``ask_user_request`` frame, blocks on the registered future, and
when the HTTP resolver fires it returns the answers verbatim as the tool
result. The agent reads the structured answer from its tool-result envelope
— no deny-with-message hijack, no permission-card semantics.

Why split this from ``permissions.py`` rather than overload that module:

- Permission flow returns ``PermissionResultAllow | PermissionResultDeny`` —
  a binary signal. ask_user returns a payload of selected options, which
  doesn't fit either result class.
- The cancel-on-turn-end behaviour differs: a stranded permission resolves to
  deny so the SDK unblocks; a stranded ask_user resolves to an empty
  ``answers=[]`` so the tool returns a benign ``ok=false`` envelope rather
  than tripping a permission denial.
- Keeping the modules separate prevents the "ask gate" abstraction from
  collapsing — they share a registry pattern, not a contract.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any


# Module-level pending registry keyed by ``(chat_id, request_id)``. The tool
# body awaits its future; the HTTP route resolves it. Lives at module scope
# because ``ChatService`` is instantiated fresh per request (see
# permissions.py docstring for the same reasoning).
_pending: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
_pending_lock = asyncio.Lock()


async def request_user_answer(
    *,
    chat_id: str,
    questions: list[dict[str, Any]],
    sse_writer,
) -> dict[str, Any]:
    """Emit an ``ask_user_request`` SSE event and block until the user
    answers via ``resolve_user_answer``.

    Returns the answers payload as ``{answers: [...]}`` on success. If no
    ``sse_writer`` is bound (tool called outside a live chat turn — e.g. via
    the public ``/v1/extract`` fast-path), returns an ``ok=false`` envelope
    instead of waiting forever.
    """
    if sse_writer is None:
        return {
            "ok": False,
            "error": {
                "error_code": "ask_user_no_session",
                "error_message_en": (
                    "ask_user requires an active chat session; no SSE writer "
                    "is in scope"
                ),
            },
        }

    request_id = uuid.uuid4().hex[:12]
    loop = asyncio.get_event_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    async with _pending_lock:
        _pending[(chat_id, request_id)] = future

    payload: dict[str, Any] = {
        "request_id": request_id,
        "questions": questions,
    }
    await sse_writer("ask_user_request", payload)

    try:
        result = await future
    finally:
        async with _pending_lock:
            _pending.pop((chat_id, request_id), None)

    # ``cancelled`` short-circuit: the chat turn ended before the user
    # answered. Surface it as a non-fatal error envelope so the tool result
    # is interpretable; the agent's next turn can decide whether to re-ask.
    if result.get("cancelled"):
        return {
            "ok": False,
            "error": {
                "error_code": "ask_user_cancelled",
                "error_message_en": (
                    result.get("reason") or "Chat turn ended before user answered."
                ),
            },
        }

    answers = result.get("answers") or []
    return {"ok": True, "answers": answers}


async def resolve_user_answer(
    *,
    chat_id: str,
    request_id: str,
    answers: list[dict[str, Any]],
    cancelled: bool = False,
    cancel_reason: str | None = None,
) -> bool:
    """Called by the HTTP route when the user submits their selection.

    Set ``cancelled=True`` to mark the request as user-redirected: the agent
    receives ``ask_user_cancelled`` (same envelope as turn-end cancel) so it
    can fall back to plain conversation. The user-redirect path is what fires
    when the user types a new message in the composer mid-prompt instead of
    picking an option.

    Returns False if the request_id is unknown or already resolved (idempotent
    no-op so a double-click can't crash the route).
    """
    async with _pending_lock:
        future = _pending.get((chat_id, request_id))
    if future is None or future.done():
        return False
    if cancelled:
        future.set_result({
            "cancelled": True,
            "reason": cancel_reason or "User redirected via composer.",
        })
    else:
        future.set_result({"answers": answers})
    return True


async def cancel_pending_ask_user(chat_id: str) -> None:
    """Drop every outstanding ask_user request for a chat — used when the
    chat turn ends so dangling futures don't linger forever. Idempotent."""
    async with _pending_lock:
        stale = [k for k in _pending if k[0] == chat_id]
        for key in stale:
            fut = _pending.pop(key, None)
            if fut and not fut.done():
                fut.set_result({
                    "cancelled": True,
                    "reason": "Chat turn ended.",
                })
