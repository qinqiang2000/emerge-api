import json
from pathlib import Path

from app.scripts.scrub_chat_logs import scrub_chat_file


def test_scrub_chat_file_redacts_in_place(tmp_path: Path) -> None:
    chat_file = tmp_path / "p_a" / "chats" / "c_x.jsonl"
    chat_file.parent.mkdir(parents=True)
    lines = [
        json.dumps({"type": "user", "text": "/publish"}),
        json.dumps({
            "type": "tool_call",
            "tool_use_id": "t1",
            "tool_name": "mcp__emerge_tools__issue_api_key",
            "tool_input": {},
            "tool_result": None,
            "ok": True,
        }),
        json.dumps({
            "type": "tool_result",
            "tool_use_id": "t1",
            "ok": True,
            "result_text": json.dumps({
                "key_plaintext": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0",
                "key_prefix": "ek_aVtq",
                "key_hash": "h",
            }),
        }),
        json.dumps({"type": "agent_text", "text": "Your key is ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0"}),
    ]
    chat_file.write_text("\n".join(lines))

    s, n = scrub_chat_file(chat_file, dry_run=False)

    assert n == 4
    assert s == 2  # tool_result + agent_text were rewritten
    text = chat_file.read_text()
    assert "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0" not in text
    assert "[REDACTED]" in text
    assert "[REDACTED-API-KEY]" in text
    # Non-secret entries unchanged
    assert "/publish" in text
    assert "ek_aVtq" in text  # the prefix in tool_result is preserved


def test_scrub_chat_file_dry_run_does_not_write(tmp_path: Path) -> None:
    chat_file = tmp_path / "p_a" / "chats" / "c_x.jsonl"
    chat_file.parent.mkdir(parents=True)
    secret_line = json.dumps({"type": "agent_text", "text": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0"})
    chat_file.write_text(secret_line)
    original = chat_file.read_text()

    s, n = scrub_chat_file(chat_file, dry_run=True)

    assert s == 1
    assert n == 1
    assert chat_file.read_text() == original  # untouched on disk


def test_scrub_chat_file_is_idempotent(tmp_path: Path) -> None:
    chat_file = tmp_path / "p_a" / "chats" / "c_x.jsonl"
    chat_file.parent.mkdir(parents=True)
    chat_file.write_text(
        json.dumps({"type": "agent_text", "text": "ek_aVtqWOOU47YxiffeqT_Rb1rBaXZQN5t0"})
    )

    scrub_chat_file(chat_file, dry_run=False)
    after_first = chat_file.read_text()
    s2, _ = scrub_chat_file(chat_file, dry_run=False)
    after_second = chat_file.read_text()

    assert s2 == 0  # nothing left to scrub
    assert after_first == after_second
