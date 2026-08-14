"""Async user-question round-trip for the ``ask_user`` MCP tool.

This mirrors the structure of ``permissions.request_permission`` — both park
their futures in a ``chat/pending.py`` registry, same chat-id-scoped cleanup —
but the semantics
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

from typing import Any

from app.chat.pending import PendingPrompts


# Module-level pending registry keyed by ``(chat_id, request_id)``. The tool
# body awaits its future; the HTTP route resolves it. Lives at module scope
# because ``ChatService`` is instantiated fresh per request (see
# permissions.py docstring for the same reasoning). The registry also retains
# the SSE payload so ``GET .../turns/{tid}/stream`` can replay an unanswered
# question to a re-attaching client — see ``chat/pending.py``.
_pending = PendingPrompts("ask_user_request")


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

    request_id, payload, future = await _pending.register(
        chat_id=chat_id,
        payload_for=lambda rid: {
            "request_id": rid,
            "questions": questions,
        },
    )
    await sse_writer("ask_user_request", payload)

    try:
        result = await future
    finally:
        await _pending.discard(chat_id, request_id)

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
    if cancelled:
        result: dict[str, Any] = {
            "cancelled": True,
            "reason": cancel_reason or "User redirected via composer.",
        }
    else:
        result = {"answers": answers}
    return await _pending.resolve(chat_id, request_id, result)


async def cancel_pending_ask_user(chat_id: str) -> None:
    """Drop every outstanding ask_user request for a chat — used when the
    chat turn ends so dangling futures don't linger forever. Idempotent."""
    await _pending.cancel_chat(
        chat_id, {"cancelled": True, "reason": "Chat turn ended."}
    )
