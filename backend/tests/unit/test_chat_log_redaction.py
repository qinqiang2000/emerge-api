import json
import pytest
from pathlib import Path

from app.chat.log import append_event
from app.workspace.paths import chats_dir


@pytest.mark.asyncio
async def test_issue_api_key_tool_result_redacted_in_jsonl(tmp_path: Path) -> None:
    # EventRedactor lives in a module that's about to be created in Task 5.
    from app.chat.redactor import EventRedactor

    pid = "p_aaaaaaaaaaaa"
    cid = "c_test"
    # The chat-log writer gates on project.json existence (tombstone for
    # mid-turn project deletion). Materialize a stub so this redaction test
    # — which only cares about scrubbing, not project lifecycle — can persist.
    pdir = tmp_path / pid
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(json.dumps({"project_id": pid, "slug": pid}))
    redactor = EventRedactor()

    parent = {
        "tool_use_id": "t_x",
        "tool_name": "mcp__emerge_tools__issue_api_key",
        "tool_input": {"project_id": pid},
        "tool_result": None,
        "ok": True,
    }
    redactor.observe("tool_call", parent)

    raw_result = {
        "tool_use_id": "t_x",
        "ok": True,
        "result_text": json.dumps({
            "key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0",
            "key_hash": "abc",
            "key_prefix": "ek_aVtqWOOU",
            "created_at": "2026-05-10T00:00:00Z",
        }),
    }
    persist_payload = redactor.scrub_for_persist("tool_result", raw_result)

    # Asserting the in-memory shape first
    parsed = json.loads(persist_payload["result_text"])
    assert parsed["key_plaintext"] == "[REDACTED]"
    assert parsed["key_prefix"] == "ek_aVtqWOOU"
    assert parsed["key_hash"] == "abc"
    assert parsed["created_at"] == "2026-05-10T00:00:00Z"

    # Belt-and-suspenders: also write through append_event and re-read
    await append_event(tmp_path, pid, cid, {"type": "tool_call", **parent})
    await append_event(tmp_path, pid, cid, {"type": "tool_result", **persist_payload})
    log_path = chats_dir(tmp_path, pid) / f"{cid}.jsonl"
    lines = [json.loads(l) for l in log_path.read_text().splitlines()]
    result_line = next(l for l in lines if l["type"] == "tool_result")
    assert "[REDACTED]" in result_line["result_text"]
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in result_line["result_text"]


def test_agent_text_scrubs_ek_keys_persist_and_sse() -> None:
    from app.chat.redactor import EventRedactor

    r = EventRedactor()
    payload = {"text": "Here is your key ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0 — save it."}

    persist = r.scrub_for_persist("agent_text", payload)
    sse = r.scrub_for_sse("agent_text", payload)

    assert "[REDACTED-API-KEY]" in persist["text"]
    assert "[REDACTED-API-KEY]" in sse["text"]
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in persist["text"]
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in sse["text"]
    # The original payload must not be mutated.
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" in payload["text"]


def test_tool_result_persist_redacted_sse_plaintext() -> None:
    """tool_result for issue_api_key: persist redacts plaintext; SSE keeps it."""
    from app.chat.redactor import EventRedactor

    r = EventRedactor()
    r.observe(
        "tool_call",
        {"tool_use_id": "t1", "tool_name": "mcp__emerge_tools__issue_api_key"},
    )
    raw = {
        "tool_use_id": "t1",
        "ok": True,
        "result_text": json.dumps({
            "key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0",
            "key_prefix": "ek_aVtq",
            "key_hash": "h",
        }),
    }

    persist = r.scrub_for_persist("tool_result", raw)
    sse = r.scrub_for_sse("tool_result", raw)

    assert "[REDACTED]" in persist["result_text"]
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in persist["result_text"]
    # SSE keeps plaintext so the frontend reveal modal can display it once.
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" in sse["result_text"]
    # Asymmetry sanity: persist and sse are different objects/strings.
    assert persist["result_text"] != sse["result_text"]


def test_tool_result_for_other_tools_passthrough() -> None:
    """Non-issue_api_key tool_result must NOT be redacted, even if its text
    contains an ek_-shaped string by coincidence."""
    from app.chat.redactor import EventRedactor

    r = EventRedactor()
    r.observe(
        "tool_call",
        {"tool_use_id": "t2", "tool_name": "mcp__emerge_tools__list_projects"},
    )
    raw = {
        "tool_use_id": "t2",
        "ok": True,
        "result_text": json.dumps({"projects": ["ek_anExampleStringThatLooksLike32xx"]}),
    }
    persist = r.scrub_for_persist("tool_result", raw)
    assert persist == raw  # passthrough
