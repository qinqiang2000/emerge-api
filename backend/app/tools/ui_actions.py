"""UI-action tools: agent-side push to the active client's review surface.

Phase 1 surface = review. Each tool validates its params, pushes a
`ui_action` SSE event through the chat-turn's `current_sse_writer`, and
returns a small confirmation payload so the agent's turn log shows what it
dispatched. The tools deliberately do NOT touch disk — they are pure
navigation commands the frontend's surfaceRouter resolves into store actions.

If no writer is in scope (tool was called outside a live chat turn — e.g.
via the public `/v1/extract` fast-path), the emit step returns an `ok=false`
envelope rather than crashing; the agent can surface the error to the user.
"""
from __future__ import annotations

import time
from typing import Any

from app.chat.sse_context import current_sse_writer


class UIActionWriterMissing(RuntimeError):
    """`current_sse_writer.get()` returned None — the tool was invoked outside
    a live chat turn so there is no client to push to."""


async def _emit(action: str, params: dict[str, Any]) -> dict[str, Any]:
    """Push a `ui_action` SSE frame, return the confirmation payload.

    Returns `{ok, action, params, ts}` on success; on missing writer returns
    `{ok: false, error: {error_code, error_message_en}}` so the agent gets a
    proper error envelope instead of an uncaught exception.
    """
    writer = current_sse_writer.get()
    if writer is None:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_no_session",
                "error_message_en": (
                    f"ui_action {action!r} requires an active chat session; "
                    f"no SSE writer is in scope"
                ),
            },
        }
    ts = int(time.time())
    await writer("ui_action", {
        "type": "ui_action",
        "action": action,
        "params": params,
        "ts": ts,
    })
    return {"ok": True, "action": action, "params": params, "ts": ts}


async def ui_open_review(slug: str, filename: str) -> dict[str, Any]:
    """Open review mode on `filename` from the chat surface — the agent-side
    twin of clicking the doc row in the spine. The frontend surfaceRouter
    resolves this to `navigateToReview` (URL push, back-button friendly), so
    the overlay opens exactly as if the user had clicked."""
    if not isinstance(filename, str) or not filename:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_invalid_param",
                "error_message_en": (
                    f"filename must be a non-empty string, got {filename!r}"
                ),
            },
        }
    return await _emit("review:open", {"slug": slug, "filename": filename})


async def ui_goto_page(slug: str, filename: str, page: int) -> dict[str, Any]:
    """Tell the review viewer to jump to `page` (1-indexed). The frontend
    surfaceRouter clamps to [1, page_count] so passing a slightly-off page
    still navigates somewhere sensible."""
    if not isinstance(page, int) or page < 1:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_invalid_param",
                "error_message_en": f"page must be a positive int, got {page!r}",
            },
        }
    return await _emit("review:goto_page", {
        "slug": slug, "filename": filename, "page": page,
    })


async def ui_set_active_field(
    slug: str, filename: str, path: str,
) -> dict[str, Any]:
    """Focus a specific field row in the FieldEditor. `path` follows the
    `field` or `field[i].subfield` notation the editor exposes."""
    if not isinstance(path, str) or not path:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_invalid_param",
                "error_message_en": f"path must be a non-empty string, got {path!r}",
            },
        }
    return await _emit("review:set_active_field", {
        "slug": slug, "filename": filename, "path": path,
    })


async def ui_set_active_tab(
    slug: str, filename: str, tab_key: str,
) -> dict[str, Any]:
    """Switch the annotation/experiment tab strip. `tab_key='active'` selects
    the saved annotation; any other value is interpreted as an experiment_id."""
    if not isinstance(tab_key, str) or not tab_key:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_invalid_param",
                "error_message_en": (
                    f"tab_key must be a non-empty string, got {tab_key!r}"
                ),
            },
        }
    return await _emit("review:set_active_tab", {
        "slug": slug, "filename": filename, "tab_key": tab_key,
    })


async def ui_set_active_entity(
    slug: str, filename: str, idx: int,
) -> dict[str, Any]:
    """Switch the entity tab in a multi-entity doc. `idx` is 0-indexed."""
    if not isinstance(idx, int) or idx < 0:
        return {
            "ok": False,
            "error": {
                "error_code": "ui_action_invalid_param",
                "error_message_en": f"idx must be a non-negative int, got {idx!r}",
            },
        }
    return await _emit("review:set_active_entity", {
        "slug": slug, "filename": filename, "idx": idx,
    })
