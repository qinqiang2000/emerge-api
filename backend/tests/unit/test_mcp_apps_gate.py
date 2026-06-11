"""B5a — MCP Apps hello-world gate (plans/2026-06-11-audit-board.md §B5a).

Verifies the server-side half of the gate: with EMERGE_MCP_APPS on,
`read_audit_report`'s tools/list entry carries `_meta.ui.resourceUri` and the
`ui://emerge/hello.html` resource is listed/readable with the spec mimeType
`text/html;profile=mcp-app`. Default-off leaves the surface untouched.
Real-machine rendering (Claude Desktop) is the human-dogfood half.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.config import get_settings
from app.mcp_server import _APPS_MIME, _BOARD_APP_BASE, _HELLO_APP_URI, _board_app_uri, build_mcp_server

pytestmark = pytest.mark.anyio


def _build_server():
    return build_mcp_server(
        workspace=get_settings().workspace_root,
        provider=AsyncMock(),
        job_runner=AsyncMock(),
    )


async def _list_tools(server):
    from mcp.types import ListToolsRequest

    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return result.root.tools


async def _list_resources(server):
    from mcp.types import ListResourcesRequest

    handler = server.request_handlers[ListResourcesRequest]
    result = await handler(ListResourcesRequest(method="resources/list"))
    return result.root.resources


async def _read_resource(server, uri: str):
    from mcp.types import ReadResourceRequest, ReadResourceRequestParams

    handler = server.request_handlers[ReadResourceRequest]
    return await handler(
        ReadResourceRequest(
            method="resources/read", params=ReadResourceRequestParams(uri=uri)
        )
    )


def _audit_report_tool(tools):
    from app.tools import SERVICE_PREFIX

    matches = [
        t for t in tools if t.name.removeprefix(SERVICE_PREFIX) == "read_audit_report"
    ]
    assert len(matches) == 1
    return matches[0]


async def test_flag_off_no_meta_no_resources() -> None:
    server = _build_server()
    tool = _audit_report_tool(await _list_tools(server))
    assert not (tool.meta or {}).get("ui")
    assert await _list_resources(server) == []
    from mcp import McpError

    with pytest.raises(McpError):
        await _read_resource(server, _HELLO_APP_URI)


async def test_flag_on_declares_ui_and_serves_apps(monkeypatch) -> None:
    monkeypatch.setenv("EMERGE_MCP_APPS", "1")
    server = _build_server()

    # tools/list: read_audit_report carries _meta.ui.resourceUri → BOARD app
    # (wire alias `_meta` — assert the serialized shape hosts parse).
    tool = _audit_report_tool(await _list_tools(server))
    assert tool.meta["ui"]["resourceUri"] == _board_app_uri()
    assert tool.meta["ui"]["resourceUri"].startswith(_BOARD_APP_BASE + "?v=")
    wire = tool.model_dump(by_alias=True, exclude_none=True)
    assert wire["_meta"]["ui"]["resourceUri"] == _board_app_uri()

    # resources/list + resources/read: board + hello, spec mimeType.
    resources = await _list_resources(server)
    uris = {str(r.uri) for r in resources}
    assert uris == {_board_app_uri(), _HELLO_APP_URI}
    assert all(r.mimeType == _APPS_MIME for r in resources)
    # board resource declares the CSP allow-list — without it the Apps
    # iframe (deny-all sandbox) blocks every data/page fetch.
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "https://x.example")
    board = next(r for r in await _list_resources(server)
                 if str(r.uri) == _board_app_uri())
    csp = (board.meta or {})["ui"]["csp"]
    assert csp["connectDomains"] == ["https://x.example"]
    assert csp["resourceDomains"] == ["https://x.example"]
    for uri, marker in ((_board_app_uri(), "board-view"), (_HELLO_APP_URI, "hello")):
        result = await _read_resource(server, uri)
        (content,) = result.root.contents
        assert content.mimeType == _APPS_MIME
        assert "ui/initialize" in content.text
        assert "ui/notifications/initialized" in content.text
        assert marker in content.text
    # contents-side CSP (resources/read) — hosts may honor either side; the
    # wire shape must carry _meta.ui.csp on the board contents.
    board_read = await _read_resource(server, _board_app_uri())
    (bc,) = board_read.root.contents
    wire_bc = bc.model_dump(by_alias=True, exclude_none=True)
    assert wire_bc["_meta"]["ui"]["csp"]["connectDomains"] == ["https://x.example"]


async def test_flag_on_other_tools_unmarked(monkeypatch) -> None:
    monkeypatch.setenv("EMERGE_MCP_APPS", "1")
    server = _build_server()
    from app.tools import SERVICE_PREFIX

    for t in await _list_tools(server):
        if t.name.removeprefix(SERVICE_PREFIX) != "read_audit_report":
            assert not (t.meta or {}).get("ui"), t.name
