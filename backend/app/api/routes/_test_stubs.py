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


# Deterministic stub plaintext used by the publish-modal e2e. Length matches
# the production format (`ek_` + 32 url-safe chars) so chat-store / modal
# assumptions stay realistic. NEVER reuse this value in any prod-touching code.
_PUBLISH_STUB_KEY = "ek_stubbedkey0123456789ABCDEF01234"


@router.post("/lab/chat")
async def stub_chat(body: StubBody) -> EventSourceResponse:
    msg = body.user_message.lstrip()
    is_publish = msg.startswith("/publish")

    async def gen_default():
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

    async def gen_publish():
        # Mirror the real M3 flow: tool_call (no inline result) + paired
        # tool_result events. The chat store relies on this pairing to detect
        # the issue_api_key plaintext and route it to the reveal modal while
        # redacting the chat-events copy.
        yield {"event": "user_acknowledged", "data": json.dumps({"text": body.user_message})}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "Running readiness check…"
        })}
        readiness = {
            "checks": [
                {"key": "schema_non_empty", "status": "pass", "detail": "2 fields"},
                {"key": "reviewed_and_f1", "status": "pass",
                 "detail": "macro_f1=1.000 (threshold 0.7); n_reviewed=3"},
                {"key": "reviewed_fields_in_schema", "status": "pass",
                 "detail": "all reviewed fields are in schema"},
                {"key": "no_running_jobs", "status": "pass", "detail": "no running jobs"},
                {"key": "contract_diff_compat", "status": "pass",
                 "detail": "no prior active version (first publish)"},
            ],
            "soft_warnings": [],
            "hard_pass": True,
            "macro_f1": 1.0,
            "n_reviewed": 3,
        }
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_pub_readiness",
            "tool_name": "mcp__emerge_tools__readiness_check",
            "tool_input": {"project_id": body.project_id},
            "tool_result": json.dumps(readiness),
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "All checks passed. Freezing v1…"
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_pub_freeze",
            "tool_name": "mcp__emerge_tools__freeze_version",
            "tool_input": {"project_id": body.project_id},
            "tool_result": None,
            "ok": True,
        })}
        yield {"event": "tool_result", "data": json.dumps({
            "tool_use_id": "tu_pub_freeze",
            "result_text": json.dumps({"version_id": "v1"}),
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "v1 frozen. Issuing API key…"
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_pub_key",
            "tool_name": "mcp__emerge_tools__issue_api_key",
            "tool_input": {"project_id": body.project_id},
            "tool_result": None,
            "ok": True,
        })}
        reveal = {
            "key_plaintext": _PUBLISH_STUB_KEY,
            "key_hash": "f" * 64,
            "key_prefix": "ek_stubbed",
            "created_at": "2026-05-09T12:00:00Z",
        }
        yield {"event": "tool_result", "data": json.dumps({
            "tool_use_id": "tu_pub_key",
            "result_text": json.dumps(reveal),
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "API key revealed in modal. Save it now — you cannot view it again."
        })}
        yield {"event": "turn_end", "data": json.dumps({})}

    return EventSourceResponse(gen_publish() if is_publish else gen_default())
