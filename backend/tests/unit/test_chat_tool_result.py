from app.chat.service import _events_from_message
from claude_agent_sdk import (
    AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage,
)


def test_tool_use_block_emits_tool_call() -> None:
    msg = AssistantMessage(
        content=[ToolUseBlock(id="t1", name="mcp__emerge_tools__start_job",
                              input={"skill": "autoresearch", "project_id": "p_x"})],
        model="m",
    )
    events = _events_from_message(msg)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "tool_call"
    assert payload["tool_use_id"] == "t1"
    assert payload["tool_name"] == "mcp__emerge_tools__start_job"


def test_tool_result_block_emits_tool_result_event() -> None:
    msg = AssistantMessage(
        content=[
            ToolResultBlock(tool_use_id="t1", content="j_abc123def456", is_error=False),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "tool_result"
    assert payload["tool_use_id"] == "t1"
    assert payload["result_text"] == "j_abc123def456"
    assert payload["ok"] is True


def test_tool_result_block_handles_list_content() -> None:
    """SDK sometimes provides ToolResultBlock.content as a list of dicts."""
    msg = AssistantMessage(
        content=[
            ToolResultBlock(
                tool_use_id="t2",
                content=[{"type": "text", "text": "hello"}],
                is_error=False,
            ),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert events[0][1]["result_text"] == "hello"


def test_tool_result_block_is_error_propagates() -> None:
    msg = AssistantMessage(
        content=[
            ToolResultBlock(tool_use_id="t3", content="boom", is_error=True),
        ],
        model="m",
    )
    events = _events_from_message(msg)
    assert events[0][1]["ok"] is False


def test_user_message_with_tool_result_block_emits_event() -> None:
    """At runtime the SDK delivers tool results inside UserMessage, not
    AssistantMessage. The chat service must surface them so the frontend
    can pair `tool_result` to the original `tool_call` via tool_use_id."""
    msg = UserMessage(
        content=[
            ToolResultBlock(tool_use_id="t9", content="j_abc123def456", is_error=False),
        ],
    )
    events = _events_from_message(msg)
    assert len(events) == 1
    etype, payload = events[0]
    assert etype == "tool_result"
    assert payload["tool_use_id"] == "t9"
    assert payload["result_text"] == "j_abc123def456"
    assert payload["ok"] is True


def test_user_message_with_string_content_is_skipped() -> None:
    msg = UserMessage(content="echoed user prompt")
    assert _events_from_message(msg) == []
