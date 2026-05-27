from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.routes._safety import safe_chat_id, safe_slug
from app.chat.ask_user import resolve_user_answer
from app.chat.log import (
    list_chats,
    list_unbound_chats,
    read_chat_events,
    rewind_to_user,
    tombstone_unbound_chat,
)
from app.chat.permissions import resolve_permission
from app.chat.service import ChatService, _UNBOUND_SLUG
from app.config import get_settings
from app.provider import get_provider_for_model
from app.tools.promote import promote_chat_to_project
from app.workspace.ids import new_chat_id


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

    Surfaces are discriminated by ``surface``. ``review`` is the original;
    ``eval_cell`` is the peer used by EvalMatrix's drilldown inline composer.
    Both share the ``filename`` / ``field`` identity fields; the rest are
    surface-specific and filled in opportunistically when the snapshotter
    has them.
    """

    # 'review' (review overlay chat column) or 'eval_cell' (drilldown
    # inline composer). Future surfaces ('home', 'schema', 'docs',
    # 'experiments', 'publish') get added here.
    surface: str = "review"
    # ── identity (both surfaces) ──────────────────────────────────────
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
    # ── eval_cell-only ────────────────────────────────────────────────
    # `eval_ts` is the score-run timestamp the drilldown is anchored to.
    # `truth` / `pred` carry the raw cell values; `status` mirrors
    # CellVerdict.status; `verdict_reason` echoes the judge_reason when
    # the verdict came from the LLM judge. `entity_idx` is the per-doc
    # entity index (a peer of `entity_index` — kept distinct to mirror
    # the frontend's CellVerdict shape exactly).
    eval_ts: str | None = None
    truth: Any = None
    pred: Any = None
    status: str | None = None
    verdict_reason: str | None = None
    entity_idx: int | None = None


def _get_chat_service() -> ChatService:
    """Build the per-request :class:`ChatService`.

    Still exported (and consumed via lazy import by
    :mod:`app.api.routes.turns`) because turning the import into a top-level
    statement would create a cycle with :mod:`app.api.routes.chat` ↔
    :mod:`app.api.routes.turns`. Kept here so that anything else in the
    chat-routes module can pick it up alongside ``SurfaceContext`` from one
    place.
    """
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
    )


# ── Unbound chats (Phase 1 backend) ───────────────────────────────────────
# `/lab/chats` (no slug) is the address of a chat that hasn't been bound to a
# project. Mint with POST → carries until `/promote` migrates the jsonl + meta
# + attachments under a new project slug. Coexists with the legacy `p_unset`
# mint behaviour for Phase 1 — frontend cutover lands in Phase 2.
#
# Route ordering note: these handlers MUST stay declared BEFORE the existing
# `GET /lab/chats/{slug}` / `GET /lab/chats/{slug}/{chat_id}` so a chat_id
# in `/lab/chats/{chat_id}/events` doesn't get matched as a (slug, chat_id)
# pair (the literal `events` would otherwise fall into the `chat_id`
# placeholder and trip `safe_chat_id` with a 400). FastAPI route resolution
# is purely positional.


class PromoteUnboundBody(BaseModel):
    name: str
    slug: str | None = None


@router.post("/lab/chats")
async def lab_unbound_chat_create() -> dict[str, str]:
    """Mint a fresh unbound chat id. No storage is created yet — the very
    first `append_event` (or `ensure_chat_meta`) materialises `_chats/<cid>.*`.
    The HTTP layer is responsible for the id; the frontend then routes the
    user to `/c/<cid>` (Phase 2)."""
    cid = new_chat_id()
    return {"chat_id": cid}


@router.get("/lab/chats")
async def lab_unbound_chat_list() -> list[dict[str, Any]]:
    """List all unbound chats under `_chats/`, newest first. Returns a list of
    `{chat_id, label, kind, ts_iso, n_events, attachment_count}` so the
    Phase-2 frontend can render the empty-hero "Recent conversations" strip
    + the scope-aware chat-history popover without N round-trips."""
    workspace_root = get_settings().workspace_root
    return list_unbound_chats(workspace_root)


@router.get("/lab/chats/{chat_id}/events")
async def lab_unbound_chat_history(chat_id: str) -> dict[str, Any]:
    """Replay the unbound chat's event log. Mirrors
    `GET /lab/chats/{slug}/{chat_id}` for project chats; the trailing
    `/events` segment disambiguates from the slug-keyed route."""
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    return {"events": read_chat_events(workspace_root, _UNBOUND_SLUG, chat_id)}


@router.post("/lab/chats/{chat_id}/promote")
async def lab_unbound_chat_promote(
    chat_id: str, body: PromoteUnboundBody,
) -> dict[str, str]:
    """Bind an unbound chat to a fresh project. Atomically relocates the
    chat's jsonl + meta + attachments under the new project's `chats/`.
    Returns `{slug, project_id}`. After this call the chat is reachable at
    `/p/<slug>` and the unbound slot is tombstoned."""
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    out = await promote_chat_to_project(
        workspace_root,
        chat_id,
        name=body.name,
        slug=body.slug,
    )
    return out


@router.delete("/lab/chats/{chat_id}")
async def lab_unbound_chat_delete(chat_id: str) -> dict[str, Any]:
    """Tombstone an unbound chat: unlink jsonl + meta + per-chat dir, then
    drop a `.tombstone` marker so trailing SDK events from a still-running
    turn are silently dropped. Idempotent: deleting an already-tombstoned
    chat returns `{ok: true}` with `existed=false` only when there was
    nothing at all on disk."""
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    existed = tombstone_unbound_chat(workspace_root, chat_id)
    return {"ok": True, "existed": existed}


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


class AskUserAnswerEntry(BaseModel):
    """One question's worth of answer: which option(s) the user picked.

    ``question_index`` matches the position in the original ``questions[]``
    array. ``selected`` carries both index AND label — duplicating is cheap
    and lets the agent read whichever it prefers without needing the original
    payload in scope.
    """

    question_index: int
    selected: list[dict[str, Any]]


class AskUserAnswerBody(BaseModel):
    """User's reply to an ``ask_user_request`` SSE event.

    ``cancelled=true`` signals the user typed a new message in the composer
    instead of picking an option — resolves the agent's await with an
    ``ask_user_cancelled`` envelope so the next turn picks up plain
    conversation. When ``cancelled`` the ``answers`` field is ignored
    (caller can send an empty list).
    """

    answers: list[AskUserAnswerEntry] = []
    cancelled: bool = False


@router.post("/lab/chats/{chat_id}/ask_user/{request_id}")
async def lab_chat_ask_user(
    chat_id: str,
    request_id: str,
    body: AskUserAnswerBody,
) -> dict[str, Any]:
    """Resolve a pending ``ask_user_request`` keyed by ``(chat_id, request_id)``.

    Idempotent — a duplicate POST (double-click) returns ``ok=false`` with
    ``reason='unknown_or_resolved'`` instead of raising.
    """
    safe_chat_id(chat_id)
    resolved = await resolve_user_answer(
        chat_id=chat_id,
        request_id=request_id,
        answers=[a.model_dump() for a in body.answers],
        cancelled=body.cancelled,
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
