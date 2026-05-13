from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.routes._safety import safe_chat_id, safe_project_id
from app.chat.log import list_chats, read_chat_events, rewind_to_user
from app.chat.service import ChatService
from app.config import get_settings
from app.provider import get_provider_for_model


router = APIRouter()


class ChatBody(BaseModel):
    project_id: str
    chat_id: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None


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
            project_id=body.project_id,
            chat_id=body.chat_id,
            user_message=body.user_message,
            attachments=body.attachments,
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


@router.get("/lab/chats/{project_id}")
async def lab_chat_list(project_id: str) -> list[dict[str, Any]]:
    safe_project_id(project_id)
    workspace_root = get_settings().workspace_root
    return list_chats(workspace_root, project_id)


@router.get("/lab/chats/{project_id}/{chat_id}")
async def lab_chat_history(project_id: str, chat_id: str) -> dict[str, Any]:
    safe_project_id(project_id)
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    return {"events": read_chat_events(workspace_root, project_id, chat_id)}


_REWIND_PROJECT_ID = re.compile(r"^(p_unset|p_[a-z0-9]{12})$")


@router.post("/lab/chats/{project_id}/{chat_id}/rewind")
async def lab_chat_rewind(
    project_id: str,
    chat_id: str,
    target_user_index: int | None = None,
) -> dict[str, Any]:
    """Truncate events.jsonl at a `user` line and clear the SDK session
    sidecar. Powers retry / edit on any user bubble.

    `target_user_index` is a 0-indexed ordinal among user lines. When omitted,
    truncates at the last user line (composer-after-Stop default).

    Accepts `p_unset` alongside committed `p_*` ids: pre-adoption chats live
    under `workspace/p_unset/chats/{chat_id}.jsonl` (see ChatService.chat_turn)
    and must be rewindable too — the rewind operation is conceptually
    chat-scoped, not project-scoped."""
    if not _REWIND_PROJECT_ID.match(project_id):
        raise HTTPException(status_code=400, detail="invalid project_id")
    safe_chat_id(chat_id)
    workspace_root = get_settings().workspace_root
    new_size = rewind_to_user(
        workspace_root, project_id, chat_id, target_user_index=target_user_index,
    )
    return {"ok": True, "rewound_to": new_size}
