"""Remote tool-call usage logging (P4 prep — data-driven convergence).

Locks: headless calls are logged + aggregated; the browser-chat surface is NOT
logged (operator ≠ teammate); recording is best-effort (never raises).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

from mcp.types import CallToolRequest, CallToolRequestParams

from app.config import get_settings
from app.tools import build_emerge_mcp
from app.tools.usage import aggregate, record_tool_call
from app.workspace.paths import usage_log_path


def _team_ws(workspace: Path) -> Path:
    ws = workspace / "teams" / "acme"
    ws.mkdir(parents=True)
    return ws


async def _call(server, name: str, args: dict) -> None:
    handler = server.request_handlers[CallToolRequest]
    await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=args),
    ))


def _build(workspace: Path, headless: bool):
    return build_emerge_mcp(
        workspace=workspace, provider=AsyncMock(), job_runner=AsyncMock(), headless=headless,
    )["instance"]


# --- record + aggregate -----------------------------------------------------

def test_record_and_aggregate(workspace: Path) -> None:
    ws = _team_ws(workspace)
    record_tool_call(ws, "ws_list")
    record_tool_call(ws, "ws_list")
    record_tool_call(ws, "add_model")
    agg = aggregate(get_settings().workspace_root)
    assert agg["acme"]["ws_list"] == 2
    assert agg["acme"]["add_model"] == 1


def test_record_is_best_effort(monkeypatch, workspace: Path) -> None:
    # a logging failure must never propagate (would break the tool call)
    import app.tools.usage as usage_mod
    monkeypatch.setattr(usage_mod, "usage_log_path", lambda root: (_ for _ in ()).throw(OSError("boom")))
    record_tool_call(workspace, "ws_list")  # must not raise


# --- headless wraps; chat does not ------------------------------------------

async def test_headless_calls_are_logged(workspace: Path) -> None:
    ws = _team_ws(workspace)
    server = _build(ws, headless=True)
    # dispatch uses the prefixed headless name; the log keeps the bare name
    # (telemetry continuity across the prefix change)
    await _call(server, "emerge_ws_list", {"path": "."})
    lines = usage_log_path(get_settings().workspace_root).read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["team"] == "acme" and rec["tool"] == "ws_list"


async def test_browser_chat_is_not_logged(workspace: Path) -> None:
    ws = _team_ws(workspace)
    server = _build(ws, headless=False)  # operator's own chat — must not log
    # get_surface_state exists on both surfaces and needs no real provider
    await _call(server, "get_surface_state", {})
    assert not usage_log_path(get_settings().workspace_root).exists()
