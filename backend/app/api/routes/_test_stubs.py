"""Test-only routes used by the Playwright e2e to avoid hitting Anthropic.

These shadow the real M11 turn-as-resource routes (``POST /lab/chats/{cid}/turns``
+ ``GET .../stream``, plus ``cancel`` / ``turn_state``) when the backend is
launched with ``EMERGE_TEST_MODE=1``. FastAPI matches handlers in registration
order, so this router is included **before** ``app.api.routes.turns`` in
:mod:`app.main`, letting the stubs intercept the same URLs the frontend now
exercises after the M11-followup-D shim removal. No LLM is invoked.

Branching mirrors the original ``/lab/chat`` stub: ``/publish`` drives the
publish-modal e2e (readiness → freeze → issue_api_key → reveal); ``/extract``
drives the extract-flow e2e; everything else falls through to the
walking-skeleton default (create_project + extract_one + agent_text).

State across POST start → GET stream: the message we branch on lives in the
POST body, but the GET stream is a separate request. We stash the most recent
``user_message`` for each ``(cid, turn_id)`` in a module-level dict at POST
time and read it at GET time. This is e2e-only — concurrency / leaks don't
matter for Playwright runs and the dict resets when the test server restarts.
"""
import json
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse


router = APIRouter()


class StubStartTurnBody(BaseModel):
    """Mirror of :class:`app.api.routes.turns.StartTurnBody` minus the
    optional ``surface_context`` typing (the stub doesn't care about its
    shape — it never threads it back). ``slug`` is whichever destination
    the frontend chose: a real project slug, the ``_chats`` unbound
    sentinel, or the ``p_unset`` legacy auto-mint handle. We surface it
    in tool_input so any e2e that asserts on tool args still sees a
    realistic value."""

    slug: str
    user_message: str
    attachments: list[dict[str, Any]] | None = None
    surface_context: dict[str, Any] | None = None


# Deterministic stub turn_id. Length / shape mirrors real ids so the chat
# store's localStorage assertions and any future "is this a turn id"
# heuristic don't care that it's a stub. Reused across every POST start —
# the e2e never reads it back as a unique handle (it goes from the start
# response straight into a GET stream against the same handler).
_STUB_TURN_ID = "tstubturn1234567"


# Deterministic stub plaintext used by the publish-modal e2e. Length matches
# the production format (`ek_` + 32 url-safe chars) so chat-store / modal
# assumptions stay realistic. NEVER reuse this value in any prod-touching code.
_PUBLISH_STUB_KEY = "ek_stubbedkey0123456789ABCDEF01234"


# In-memory pending-message cache. The POST start handler captures
# ``user_message`` for each (cid, tid) so the GET stream handler can branch
# on it (/publish vs /extract vs default). The frontend doesn't echo the
# message into the GET URL, so we have to bridge it server-side. Single-
# process, e2e-only — never used outside ``EMERGE_TEST_MODE=1``.
_PENDING_MSG: dict[tuple[str, str], str] = {}


@router.post("/lab/chats/{cid}/turns")
async def stub_start_turn(
    cid: str, body: StubStartTurnBody,
) -> dict[str, str]:
    """Stub for :func:`app.api.routes.turns.start_turn`.

    Returns a deterministic ``turn_id`` so the frontend's two-phase
    ``startTurn + attachStream`` flow has a handle. Stashes the
    ``user_message`` so the subsequent ``GET .../stream`` can branch on it
    (/publish vs /extract vs default), since the GET doesn't echo the
    message back to the server.
    """
    _PENDING_MSG[(cid, _STUB_TURN_ID)] = body.user_message
    return {"turn_id": _STUB_TURN_ID, "status": "running"}


@router.get("/lab/chats/{cid}/turns/{tid}/stream")
async def stub_stream_turn(
    cid: str, tid: str, after_offset: int = 0,
) -> EventSourceResponse:
    """Stub for :func:`app.api.routes.turns.stream_turn`.

    Reads the message recorded by the matching POST start, then emits the
    same canned event sequence the pre-M11 ``/lab/chat`` stub did. Three
    branches:

    * ``/publish`` → publish-modal flow (readiness → freeze → issue_api_key
      with one-time plaintext reveal).
    * ``/extract`` → extract-flow stub (list_docs + parallel extract_one).
    * else        → walking-skeleton default (create_project +
                    extract_one + ``Stub run complete``).
    """
    msg = _PENDING_MSG.pop((cid, tid), "").lstrip()
    is_publish = msg.startswith("/publish")
    is_extract = msg.startswith("/extract")

    async def gen_default():
        yield {"event": "user_acknowledged", "data": json.dumps({"text": msg})}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "create_project",
            "tool_input": {"name": "stubbed"},
            "tool_result": {"project_id": "p_stubbed1234", "slug": "stubbed"},
            "ok": True,
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_name": "extract_one",
            "tool_input": {"slug": "stubbed", "filename": "stub.pdf"},
            "tool_result": {"entities": []},
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
        yield {"event": "user_acknowledged", "data": json.dumps({"text": msg})}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "Running readiness check…"
        })}
        readiness = {
            "checks": [
                {"key": "schema_non_empty", "status": "pass", "detail": "2 fields"},
                {"key": "reviewed_and_accuracy", "status": "pass",
                 "detail": "field_accuracy_macro=1.000 (threshold 0.75); n_reviewed=3"},
                {"key": "reviewed_fields_in_schema", "status": "pass",
                 "detail": "all reviewed fields are in schema"},
                {"key": "no_running_jobs", "status": "pass", "detail": "no running jobs"},
                {"key": "contract_diff_compat", "status": "pass",
                 "detail": "no prior active version (first publish)"},
            ],
            "soft_warnings": [],
            "hard_pass": True,
            "field_accuracy_macro": 1.0,
            "macro_f1": 1.0,
            "n_reviewed": 3,
        }
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_pub_readiness",
            "tool_name": "mcp__emerge_tools__readiness_check",
            "tool_input": {"slug": "stubbed"},
            "tool_result": json.dumps(readiness),
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "All checks passed. Freezing v1…"
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_pub_freeze",
            "tool_name": "mcp__emerge_tools__freeze_version",
            "tool_input": {"slug": "stubbed"},
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
            "tool_input": {"slug": "stubbed"},
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

    async def gen_extract():
        yield {"event": "user_acknowledged", "data": json.dumps({"text": msg})}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "Running batch extract..."
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_ext_list",
            "tool_name": "mcp__emerge_tools__list_docs",
            "tool_input": {"slug": "stubbed"},
            "tool_result": "[{'filename':'a.pdf'},{'filename':'b.pdf'}]",
            "ok": True,
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_ext_a",
            "tool_name": "mcp__emerge_tools__extract_one",
            "tool_input": {"slug": "stubbed", "filename": "a.pdf"},
            "tool_result": json.dumps({"entities": [{"invoice_no": "A"}]}),
            "ok": True,
        })}
        yield {"event": "tool_call", "data": json.dumps({
            "tool_use_id": "tu_ext_b",
            "tool_name": "mcp__emerge_tools__extract_one",
            "tool_input": {"slug": "stubbed", "filename": "b.pdf"},
            "tool_result": json.dumps({"entities": [{"invoice_no": "B"}]}),
            "ok": True,
        })}
        yield {"event": "agent_text", "data": json.dumps({
            "text": "**Done.** Extracted 2 docs successfully."
        })}
        yield {"event": "turn_end", "data": json.dumps({})}

    if is_publish:
        return EventSourceResponse(gen_publish())
    if is_extract:
        return EventSourceResponse(gen_extract())
    return EventSourceResponse(gen_default())


@router.post("/lab/chats/{cid}/turns/{tid}/cancel")
async def stub_cancel_turn(cid: str, tid: str) -> dict[str, str]:
    """Stub for :func:`app.api.routes.turns.cancel_turn`. Always reports
    ``cancelled`` — the frontend fires cancel as fire-and-forget on
    composer-after-Stop and mid-prompt redirects and the e2e doesn't
    distinguish ``not_found`` from ``cancelled`` for any assertion."""
    _PENDING_MSG.pop((cid, tid), None)
    return {"status": "cancelled"}


@router.get("/lab/chats/{cid}/turn_state")
async def stub_turn_state(cid: str) -> dict[str, Any]:
    """Stub for :func:`app.api.routes.turns.turn_state`. Always reports
    "no live turn" — the e2e never enters mid-turn so the re-attach
    probe should always be a no-op. ``last_offset=0`` matches an empty
    events.jsonl, which is what the test workspace starts with for any
    chat the e2e creates fresh."""
    return {"active_turn_id": None, "status": None, "last_offset": 0}
