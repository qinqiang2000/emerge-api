"""Test-only routes used by the Playwright e2e to avoid hitting Anthropic."""
import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


router = APIRouter()


class StubBody(BaseModel):
    project_id: str
    chat_id: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None


@router.post("/lab/chat")
async def stub_chat(body: StubBody) -> EventSourceResponse:
    async def gen():
        yield {"event": "user_acknowledged", "data": json.dumps({"text": body.user_message})}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "create_project",
            "tool_input": {"name": "stubbed"},
            "tool_result": {"project_id": "p_stub"},
            "ok": True,
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "extract_batch",
            "tool_input": {"project_id": "p_stub", "doc_ids": []},
            "tool_result": {"ok_count": 0, "err_count": 0, "per_doc": {}},
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "Stub run complete. (M1 e2e — no real LLM call.)"
        })}
        yield {"event": "turn_end", "data": json.dumps({})}
    return EventSourceResponse(gen())
