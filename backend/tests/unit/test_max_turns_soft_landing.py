"""Turn-budget exhaustion is a handover, not an error.

Dogfood 2026-08-10 (prod): a turn spent its whole budget discovering how to
deliver a file, then surfaced as `error_max_turns after 21 turns` — every
intermediate result discarded, nothing said to the user. A colleague who thinks
for twenty steps tells you where they got to.
"""
from __future__ import annotations

import pytest
from claude_agent_sdk import ResultMessage

from app.chat.service import _events_from_message, _is_max_turns_result


def _result(**kw) -> ResultMessage:
    base = dict(
        subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
        num_turns=1, session_id="s1",
    )
    base.update(kw)
    return ResultMessage(**base)


def test_terminal_reason_is_the_primary_discriminator() -> None:
    msg = _result(subtype="success", is_error=True, terminal_reason="max_turns")
    assert _is_max_turns_result(msg) is True


def test_legacy_subtype_still_recognised() -> None:
    """Older CLIs report `terminal_reason=None`; the bundled CLI version is not
    pinned by emerge, so the legacy path has to keep working."""
    msg = _result(subtype="error_max_turns", is_error=True, terminal_reason=None)
    assert _is_max_turns_result(msg) is True


@pytest.mark.parametrize(
    "kw",
    [
        {"subtype": "error_during_execution", "terminal_reason": "completed"},
        {"subtype": "success", "terminal_reason": "aborted_streaming"},
        {"subtype": "error", "terminal_reason": None},
    ],
)
def test_real_failures_are_not_mistaken_for_budget_exhaustion(kw) -> None:
    assert _is_max_turns_result(_result(is_error=True, **kw)) is False


def test_budget_exhaustion_never_reaches_the_client_as_an_error() -> None:
    """The whole point: the user must not see `error_max_turns`. The internal
    `_`-prefixed event is filtered out of the SSE stream by `_run_into_queue`,
    which is what triggers the wrap-up instead."""
    events = _events_from_message(
        _result(subtype="error_max_turns", is_error=True, num_turns=41,
                terminal_reason="max_turns")
    )
    assert [e[0] for e in events] == ["_max_turns"]
    assert events[0][1]["num_turns"] == 41


def test_genuine_errors_still_surface() -> None:
    events = _events_from_message(
        _result(subtype="error_during_execution", is_error=True, num_turns=3)
    )
    assert [e[0] for e in events] == ["error"]
    assert events[0][1]["error_code"] == "error_during_execution"


def test_successful_result_stays_silent() -> None:
    assert _events_from_message(_result(terminal_reason="completed")) == []


def test_wrapup_turn_cannot_call_tools() -> None:
    """Without the tool ban the wrap-up would 'just quickly check one thing'
    and burn a second full budget — the exact failure it exists to end."""
    import inspect

    from app.chat import service

    src = inspect.getsource(service.ChatService._run_wrapup)
    assert "tools=[]" in src
    assert "mcp_servers={}" in src
    assert "allowed_tools=[]" in src


def test_turn_budget_is_generous_now_that_the_ceiling_is_not_a_cliff() -> None:
    from app.chat.service import _MAX_TURNS

    assert _MAX_TURNS >= 40
