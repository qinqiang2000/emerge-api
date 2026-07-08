"""UI-action tools push `ui_action` SSE frames through `current_sse_writer`
and return a confirmation payload. With no writer in scope, they return an
`ok=false` envelope rather than crashing."""
from __future__ import annotations

from typing import Any

from app.chat.sse_context import current_sse_writer
from app.tools.ui_actions import (
    ui_goto_page,
    ui_open_review,
    ui_set_active_entity,
    ui_set_active_field,
    ui_set_active_tab,
)


class _FakeWriter:
    """Captures (event_type, payload) tuples the tool emits."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


async def test_ui_goto_page_emits_event_and_returns_ok() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_goto_page(slug="x", filename="a.pdf", page=3)
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is True
    assert out["action"] == "review:goto_page"
    assert out["params"] == {"slug": "x", "filename": "a.pdf", "page": 3}
    # One ui_action frame on the wire, payload type=='ui_action'.
    assert len(fake.events) == 1
    assert fake.events[0][0] == "ui_action"
    payload = fake.events[0][1]
    assert payload["action"] == "review:goto_page"
    assert payload["params"]["page"] == 3
    assert payload["type"] == "ui_action"


async def test_ui_set_active_field_emits_event() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_set_active_field(
            slug="x", filename="a.pdf", path="line_items[0].amount",
        )
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is True
    assert out["action"] == "review:set_active_field"
    assert fake.events[0][1]["params"]["path"] == "line_items[0].amount"


async def test_ui_set_active_tab_emits_event() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_set_active_tab(
            slug="x", filename="a.pdf", tab_key="exp_abc",
        )
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is True
    assert fake.events[0][1]["params"]["tab_key"] == "exp_abc"


async def test_ui_set_active_entity_emits_event() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_set_active_entity(slug="x", filename="a.pdf", idx=1)
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is True
    assert fake.events[0][1]["params"]["idx"] == 1


async def test_ui_open_review_emits_event() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_open_review(slug="x", filename="a.pdf")
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is True
    assert out["action"] == "review:open"
    assert fake.events[0][1]["params"] == {"slug": "x", "filename": "a.pdf"}


async def test_ui_open_review_invalid_param() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_open_review(slug="x", filename="")
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is False
    assert out["error"]["error_code"] == "ui_action_invalid_param"
    assert fake.events == []


async def test_ui_goto_page_no_writer_returns_error() -> None:
    """Outside a chat turn (no writer set), the tool returns ok=false with a
    clear error code instead of crashing."""
    # Sanity: ensure no writer is in scope.
    assert current_sse_writer.get() is None
    out = await ui_goto_page(slug="x", filename="a.pdf", page=1)
    assert out["ok"] is False
    assert out["error"]["error_code"] == "ui_action_no_session"


async def test_ui_goto_page_invalid_param() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_goto_page(slug="x", filename="a.pdf", page=0)
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is False
    assert out["error"]["error_code"] == "ui_action_invalid_param"
    # No event pushed when validation rejects the call.
    assert fake.events == []


async def test_ui_set_active_field_invalid_param() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_set_active_field(slug="x", filename="a.pdf", path="")
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is False
    assert out["error"]["error_code"] == "ui_action_invalid_param"


async def test_ui_set_active_entity_invalid_param() -> None:
    fake = _FakeWriter()
    token = current_sse_writer.set(fake)
    try:
        out = await ui_set_active_entity(slug="x", filename="a.pdf", idx=-1)
    finally:
        current_sse_writer.reset(token)
    assert out["ok"] is False
    assert out["error"]["error_code"] == "ui_action_invalid_param"
