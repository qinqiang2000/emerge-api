from app.chat.stream import sse_event


def test_sse_event_basic() -> None:
    out = sse_event("agent_text", {"text": "hello"})
    assert out == 'event: agent_text\ndata: {"text": "hello"}\n\n'


def test_sse_event_multiline_text_safe() -> None:
    out = sse_event("agent_text", {"text": "line1\nline2"})
    # JSON encodes the newline; SSE structure not broken
    assert "\\n" in out
    assert out.endswith("\n\n")


def test_sse_event_unicode() -> None:
    out = sse_event("agent_text", {"text": "你好"})
    assert "你好" in out
