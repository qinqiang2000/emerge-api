"""Guard `session_id` extraction against SDK drift.

`chat.service._run_into_queue` extracts the per-turn `session_id` exclusively
from `ResultMessage.session_id` (terminal sentinel, documented field). The
prior code also probed `SystemMessage.data["session_id"]` (init event shape,
internal). These tests pin the SDK contract so a future SDK rev that
removes either surface trips here instead of silently breaking resume.
"""

from dataclasses import fields

from claude_agent_sdk import ResultMessage, SystemMessage


def test_result_message_carries_session_id() -> None:
    fnames = {f.name for f in fields(ResultMessage)}
    assert "session_id" in fnames


def test_system_message_has_no_typed_session_id() -> None:
    # SystemMessage only typed-exposes `subtype` and `data`. session_id, when
    # present, lives inside `data` as a dict key — that's the unstable surface
    # our code no longer reads from.
    fnames = {f.name for f in fields(SystemMessage)}
    assert "session_id" not in fnames
    assert "data" in fnames


def test_result_message_instance_round_trip() -> None:
    msg = ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="sess_abc",
    )
    assert msg.session_id == "sess_abc"
