"""Token-level streaming: StreamEvent → delta-event translation + the
per-block secret-scrub hold-back that keeps an `ek_<32>` key from leaking when
it spans multiple deltas.
"""
from app.chat.redactor import EventRedactor, _EK_KEY_RE, _scrub_ek_keys
from app.chat.service import _events_from_message, _SSE_ONLY_EVENTS
from claude_agent_sdk import StreamEvent


def _stream(event: dict) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="s", event=event, parent_tool_use_id=None)


# ── translation ──────────────────────────────────────────────────────────


def test_text_delta_emits_agent_text_delta() -> None:
    msg = _stream(
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "hel"}}
    )
    events = _events_from_message(msg)
    assert events == [("agent_text_delta", {"index": 0, "text": "hel"})]


def test_thinking_delta_emits_agent_thinking() -> None:
    msg = _stream(
        {"type": "content_block_delta", "index": 1,
         "delta": {"type": "thinking_delta", "thinking": "let me"}}
    )
    events = _events_from_message(msg)
    assert events == [("agent_thinking", {"index": 1, "text": "let me"})]


def test_content_block_start_emits_internal_reset_event() -> None:
    msg = _stream(
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text"}}
    )
    events = _events_from_message(msg)
    assert events == [("_block_start", {"index": 0, "block_type": "text"})]
    # Internal control events are `_`-prefixed so the run loop skips persist/SSE.
    assert events[0][0].startswith("_")


def test_tool_arg_and_signature_deltas_dropped() -> None:
    for dtype, extra in (("input_json_delta", {"partial_json": "{"}),
                         ("signature_delta", {"signature": "abc"})):
        msg = _stream(
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": dtype, **extra}}
        )
        assert _events_from_message(msg) == []


def test_subagent_text_delta_carries_parent_id() -> None:
    msg = StreamEvent(
        uuid="u", session_id="s",
        event={"type": "content_block_delta", "index": 0,
               "delta": {"type": "text_delta", "text": "x"}},
        parent_tool_use_id="agent_1",
    )
    _, payload = _events_from_message(msg)[0]
    assert payload["parent_tool_use_id"] == "agent_1"


def test_delta_events_are_marked_sse_only() -> None:
    assert "agent_text_delta" in _SSE_ONLY_EVENTS
    assert "agent_thinking" in _SSE_ONLY_EVENTS


# ── secret hold-back across deltas ───────────────────────────────────────


def _emit_stream(redactor: EventRedactor, deltas: list[str], index: int = 0) -> str:
    redactor.observe("_block_start", {"index": index})
    out = ""
    for d in deltas:
        res = redactor.scrub_for_sse("agent_text_delta", {"index": index, "text": d})
        out += res["text"]
    return out


def test_key_split_across_deltas_never_leaks() -> None:
    key = "ek_" + "A" * 32
    r = EventRedactor()
    emitted = _emit_stream(r, ["here ", "ek", "_", "A" * 10, "A" * 22, " tail"])
    assert _EK_KEY_RE.search(emitted) is None
    assert "[REDACTED-API-KEY]" in emitted
    assert key not in emitted


def test_emitted_is_always_prefix_of_finalized() -> None:
    # The frontend replaces the streaming buffer with the finalized full text,
    # so the live deltas must never diverge from a prefix of it.
    deltas = ["The valu", "e is ", "ek_" + "B" * 32, " ok"]
    r = EventRedactor()
    emitted = _emit_stream(r, deltas)
    finalized = _scrub_ek_keys({"text": "".join(deltas)})["text"]
    assert finalized.startswith(emitted)


def test_short_ek_prefix_is_not_a_key_and_flushes() -> None:
    # `ek_short ` is NOT a 32-char key — once a non-key char arrives the held
    # tail must be released verbatim.
    r = EventRedactor()
    emitted = _emit_stream(r, ["use ", "ek_short", " value", "."])
    assert emitted == "use ek_short value."


def test_block_start_resets_buffer_between_blocks() -> None:
    r = EventRedactor()
    r.observe("_block_start", {"index": 0})
    r.scrub_for_sse("agent_text_delta", {"index": 0, "text": "first"})
    # New block at the same index restarts emitted-offset tracking from zero.
    r.observe("_block_start", {"index": 0})
    res = r.scrub_for_sse("agent_text_delta", {"index": 0, "text": "second"})
    assert res["text"] == "second"


def test_index_field_stripped_from_sse_payload() -> None:
    r = EventRedactor()
    r.observe("_block_start", {"index": 0})
    res = r.scrub_for_sse("agent_text_delta", {"index": 0, "text": "hi"})
    assert "index" not in res
