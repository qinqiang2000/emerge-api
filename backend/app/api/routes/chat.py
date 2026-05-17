from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.routes._safety import safe_chat_id, safe_slug
from app.chat.log import list_chats, read_chat_events, rewind_to_user
from app.chat.permissions import resolve_permission
from app.chat.service import ChatService
from app.config import get_settings
from app.provider import get_provider_for_model


router = APIRouter()


# Sentinel: the empty-hero composer mints a project mid-turn (see
# ChatService.chat_turn). Slugs are otherwise opaque human-readable handles
# so we don't constrain their shape here — `safe_slug` handles validation.
_UNSET_SLUG = "p_unset"


class SurfaceContext(BaseModel):
    """UI-state snapshot of whichever surface the user submitted from.

    The frontend snapshots ambient state at submit time (NOT render time —
    the user may navigate mid-response) and threads it into the chat envelope.
    The chat service appends a `## Surface context` block to the system prompt
    so the agent knows what the user is looking at.

    Phase 1 only `surface='review'` exists. `filename` is the only field
    required for review; the rest are optional ambient signals the snapshotter
    fills in when they are known.
    """

    # Phase 1: only 'review' is meaningful. Future surfaces ('home', 'schema',
    # 'docs', 'experiments', 'publish') get added here.
    surface: str = "review"
    # ── review surface fields ─────────────────────────────────────────
    filename: str
    field: str | None = None
    current_value: Any = None
    entity_index: int = 0
    # ── ambient navigation state (review) ─────────────────────────────
    page: int | None = None
    page_count: int | None = None
    entity_count: int | None = None
    active_tab_key: str | None = None
    experiment_id: str | None = None


class ChatBody(BaseModel):
    # Field name kept as `project_id` for back-compat with the frontend SSE
    # request payload; the value carried is the slug (folder name) for any
    # already-committed project, or the `p_unset` sentinel for an empty-hero
    # drop where ChatService mints the project mid-turn.
    project_id: str
    chat_id: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None
    # Present only when the user submits from a surface that snapshots state
    # (currently: review overlay's chat column). When absent, the chat service
    # behaves identically to pre-Phase-B (no `## Surface context` block in the
    # system prompt).
    surface_context: SurfaceContext | None = None


def _get_chat_service() -> ChatService:
    settings = get_settings()
    # Apply optional proxy from CLAUDE_PROXY → HTTPS_PROXY/HTTP_PROXY (claude_agent_sdk picks up).
    claude_proxy = os.getenv("CLAUDE_PROXY", "").strip()
    if claude_proxy:
        os.environ.setdefault("HTTPS_PROXY", claude_proxy)
        os.environ.setdefault("HTTP_PROXY", claude_proxy)
    provider = get_provider_for_model(settings.default_extract_model)
    return ChatService(
        workspace=settings.workspace_root,
        provider=provider,
        agent_model=settings.default_agent_model,
        extract_model=settings.default_extract_model,
    )


@router.post("/lab/chat")
async def lab_chat(body: ChatBody) -> EventSourceResponse:
    svc = _get_chat_service()

    async def gen():
        async for chunk in svc.chat_turn(
            slug=body.project_id,
            chat_id=body.chat_id,
            user_message=body.user_message,
            attachments=body.attachments,
            surface_context=body.surface_context.model_dump() if body.surface_context else None,
        ):
            # sse_starlette wants {event, data} dicts; ChatService yields fully-formed
            # "event: x\ndata: y\n\n" strings. Re-parse them so sse_starlette can re-emit.
            lines = chunk.strip().split("\n")
            event_line = next((ln for ln in lines if ln.startswith("event:")), "event: message")
            data_line = next((ln for ln in lines if ln.startswith("data:")), "data: {}")
            yield {
                "event": event_line.split(":", 1)[1].strip(),
                "data": data_line.split(":", 1)[1].strip(),
            }

    return EventSourceResponse(gen())


@router.get("/lab/chats/{slug}")
async def lab_chat_list(slug: str) -> list[dict[str, Any]]:
    safe_slug(slug)
    workspace_root = get_settings().workspace_root
    return list_chats(workspace_root, slug)


@router.get("/lab/chats/{slug}/{chat_id}")
async def lab_chat_history(slug: str, chat_id: str) -> dict[str, Any]:
    safe_slug(slug)
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    return {"events": read_chat_events(workspace_root, slug, chat_id)}


class PermissionDecisionBody(BaseModel):
    """User's reply to a ``permission_request`` SSE event.

    ``decision`` is ``approve`` or ``deny``. ``scope`` is ``once`` (this single
    tool call only) or ``always`` (every subsequent call to the same
    ``tool_name`` in this chat, in-memory only — does not survive a backend
    restart). ``message`` is a free-form note surfaced to the agent on deny.
    """

    decision: str
    scope: str = "once"
    message: str | None = None


@router.post("/lab/chats/{chat_id}/permission/{request_id}")
async def lab_chat_permission(
    chat_id: str,
    request_id: str,
    body: PermissionDecisionBody,
) -> dict[str, Any]:
    """Resolve a pending ``permission_request`` keyed by ``(chat_id, request_id)``.

    Idempotent: a duplicate POST (e.g. the user double-clicks) returns
    ``{ok: false, reason: 'unknown_or_resolved'}`` rather than raising — the
    UI can ignore the loser.
    """
    safe_chat_id(chat_id)
    if body.decision not in ("approve", "deny"):
        return {
            "ok": False,
            "error_code": "invalid_decision",
            "error_message_en": "decision must be 'approve' or 'deny'",
        }
    if body.scope not in ("once", "always"):
        return {
            "ok": False,
            "error_code": "invalid_scope",
            "error_message_en": "scope must be 'once' or 'always'",
        }
    resolved = await resolve_permission(
        chat_id=chat_id,
        request_id=request_id,
        decision=body.decision,
        scope=body.scope,
        message=body.message,
    )
    if not resolved:
        return {"ok": False, "reason": "unknown_or_resolved"}
    return {"ok": True}


@router.post("/lab/chats/{slug}/{chat_id}/rewind")
async def lab_chat_rewind(
    slug: str,
    chat_id: str,
    target_user_index: int | None = None,
) -> dict[str, Any]:
    """Truncate events.jsonl at a `user` line and clear the SDK session
    sidecar. Powers retry / edit on any user bubble.

    `target_user_index` is a 0-indexed ordinal among user lines. When omitted,
    truncates at the last user line (composer-after-Stop default).

    Accepts the `p_unset` sentinel alongside committed slugs: pre-adoption
    chats live under `workspace/p_unset/chats/{chat_id}.jsonl` (see
    ChatService.chat_turn) and must be rewindable too — the rewind operation
    is conceptually chat-scoped, not project-scoped.
    """
    if slug != _UNSET_SLUG:
        safe_slug(slug)
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    new_size = rewind_to_user(
        workspace_root, slug, chat_id, target_user_index=target_user_index,
    )
    return {"ok": True, "rewound_to": new_size}
