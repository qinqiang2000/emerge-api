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
