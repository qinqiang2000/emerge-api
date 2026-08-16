"""ui_focus(target=) folds the four "point the UI at X" actions. All four had
shape (slug, filename, <one value>), all idempotent, all browser-only. The
by-product matters as much as the count: the headless narration contract
(`→ page N` / `→ focus field_name`) now lives in ONE place instead of four."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from app.tools import build_emerge_mcp, registered_tool_names


@pytest.mark.parametrize(
    "target,value,expect",
    [
        ("page", 3, {"page": 3}),
        ("field", "invoice_no", {"path": "invoice_no"}),
        ("tab", "audit", {"tab_key": "audit"}),
        ("entity", 2, {"idx": 2}),
    ],
)
async def test_ui_focus_emits_the_right_side_channel_event(
    workspace: Path, stub_provider: AsyncMock, target, value, expect, monkeypatch,
) -> None:
    fn_name = {
        "page": "ui_goto_page", "field": "ui_set_active_field",
        "tab": "ui_set_active_tab", "entity": "ui_set_active_entity",
    }[target]
    spy = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(f"app.tools.ui_actions.{fn_name}", spy)
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    handler = server["instance"].request_handlers[CallToolRequest]
    await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name="ui_focus", arguments={
            "slug": "p", "filename": "a.pdf", "target": target, "value": value,
        }),
    ))
    spy.assert_awaited_once()
    kwargs = spy.await_args.kwargs
    assert kwargs["slug"] == "p" and kwargs["filename"] == "a.pdf"
    for k, v in expect.items():
        assert kwargs[k] == v, f"{target}: expected {k}={v!r}, got {kwargs}"


def test_old_ui_names_are_gone_but_open_review_stays() -> None:
    live = registered_tool_names(headless=False)
    for old in (
        "ui_goto_page", "ui_set_active_field",
        "ui_set_active_tab", "ui_set_active_entity",
    ):
        assert old not in live
    assert "ui_focus" in live
    assert "ui_open_review" in live, "mode switch is a different verb"


def test_ui_focus_is_excluded_from_headless() -> None:
    from app.mcp_server import _HEADLESS_EXCLUDE

    assert "ui_focus" in _HEADLESS_EXCLUDE
    assert not (_HEADLESS_EXCLUDE & {
        "ui_goto_page", "ui_set_active_field",
        "ui_set_active_tab", "ui_set_active_entity",
    }), "stale bare names left in _HEADLESS_EXCLUDE"
