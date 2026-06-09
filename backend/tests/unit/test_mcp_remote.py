"""Auth + team-routing for the remote (Streamable HTTP) MCP connector.

The transport itself (initialize / list_tools filtered / list_prompts) is
covered by a live MCP-client smoke against a running backend; here we lock the
security-critical surface: the disabled mount, open-mode pass-through, and the
three-channel auth → team-workspace routing (header PAT / query PAT / reject).
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.mcp_remote import _authenticate, make_mcp_asgi
from app.auth import store
from app.auth.bootstrap import bootstrap_superuser
from app.auth.tokens import mint_pat
from app.config import get_settings
from app.workspace.paths import team_workspace_dir


def _req(headers: dict | None = None, query: str = "") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": raw,
        "query_string": query.encode(),
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


async def test_disabled_mount_returns_404() -> None:
    app = make_mcp_asgi(lambda: None)  # registry None == feature off
    sent: list[dict] = []

    async def send(m: dict) -> None:
        sent.append(m)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "POST", "path": "/",
             "headers": [], "query_string": b""}
    await app(scope, receive, send)

    assert sent[0]["status"] == 404
    assert json.loads(sent[1]["body"])["error_code"] == "mcp_remote_disabled"


async def test_open_mode_no_auth_returns_root() -> None:
    # No users bootstrapped → open mode → flat root, no credential required.
    ws = await _authenticate(_req())
    assert ws == get_settings().workspace_root


async def test_tenant_mode_without_token_rejected(workspace) -> None:
    await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    with pytest.raises(HTTPException) as ei:
        await _authenticate(_req())
    assert ei.value.status_code == 401


async def test_tenant_mode_bearer_pat_routes_to_team(workspace) -> None:
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    pat, _ = await mint_pat(workspace, su.id, "smoke")
    team = await store.get_team(workspace, su.active_team_id)
    expected = team_workspace_dir(workspace, team.slug or team.id)

    ws = await _authenticate(_req(headers={"Authorization": f"Bearer {pat}"}))
    assert ws == expected


async def test_tenant_mode_query_pat_routes_to_team(workspace) -> None:
    # In dev/open posture (no public origin → OAuth off) the ?token= shortcut works.
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    pat, _ = await mint_pat(workspace, su.id, "smoke")
    team = await store.get_team(workspace, su.active_team_id)
    expected = team_workspace_dir(workspace, team.slug or team.id)

    ws = await _authenticate(_req(query=f"token={pat}"))
    assert ws == expected


async def test_query_pat_disabled_when_oauth_enabled(workspace, monkeypatch) -> None:
    """Once OAuth is configured (public origin set), the URL ?token= path is shut
    off (leak surface) — header PAT still works, query token no longer does."""
    monkeypatch.setenv("EMERGE_PUBLIC_BASE_URL", "https://emerge.example")
    su = await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    pat, _ = await mint_pat(workspace, su.id, "smoke")
    team = await store.get_team(workspace, su.active_team_id)
    expected = team_workspace_dir(workspace, team.slug or team.id)

    # query token is ignored → 401
    with pytest.raises(HTTPException) as ei:
        await _authenticate(_req(query=f"token={pat}"))
    assert ei.value.status_code == 401
    # same PAT in the header still authenticates
    ws = await _authenticate(_req(headers={"Authorization": f"Bearer {pat}"}))
    assert ws == expected


async def test_tenant_mode_bad_token_rejected(workspace) -> None:
    await bootstrap_superuser(workspace, email="a@b.com", password="pw-12345678")
    with pytest.raises(HTTPException) as ei:
        await _authenticate(_req(headers={"Authorization": "Bearer emrg_pat_bogus"}))
    assert ei.value.status_code == 401


async def _server_tool_names(headless: bool) -> set[str]:
    from unittest.mock import AsyncMock

    from mcp.types import ListToolsRequest

    from app.tools import build_emerge_mcp

    cfg = build_emerge_mcp(
        workspace=get_settings().workspace_root,
        provider=AsyncMock(),
        job_runner=AsyncMock(),
        headless=headless,
    )
    server = cfg["instance"]
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return {t.name for t in result.root.tools}


async def test_discovery_tools_headless_only() -> None:
    """list_projects/list_docs/read_prompt appear on the headless (stdio/remote)
    server but NOT on the in-session chat server (which uses built-in Bash)."""
    discovery = {"list_projects", "list_docs", "read_prompt"}
    headless = await _server_tool_names(headless=True)
    chat = await _server_tool_names(headless=False)
    assert discovery <= headless, f"headless missing {discovery - headless}"
    assert not (discovery & chat), f"chat server leaked discovery tools {discovery & chat}"


async def test_tool_annotations_drive_client_policy() -> None:
    """Every tool carries MCP behavioural hints in the remote tools/list so a
    client (Cowork) can auto-approve reads and gate destructive ops. Crucially,
    a non-destructive mutation must say destructiveHint=False explicitly (the
    spec default is True)."""
    from unittest.mock import AsyncMock

    from mcp.types import ListToolsRequest

    from app.tools import build_emerge_mcp

    server = build_emerge_mcp(
        workspace=get_settings().workspace_root,
        provider=AsyncMock(), job_runner=AsyncMock(), headless=True,
    )["instance"]
    handler = server.request_handlers[ListToolsRequest]
    tools = (await handler(ListToolsRequest(method="tools/list"))).root.tools
    ann = {t.name: t.annotations for t in tools}

    assert all(a is not None for a in ann.values()), "every tool must be annotated"
    # read-only getter → safe to auto-approve
    assert ann["read_prompt"].readOnlyHint and not ann["read_prompt"].destructiveHint
    assert ann["list_projects"].readOnlyHint
    # irreversible / outward-facing → client should gate
    assert ann["delete_project"].destructiveHint
    assert ann["issue_api_key"].destructiveHint
    # a normal mutation is explicitly NON-destructive (overrides the spec default)
    assert ann["save_reviewed"].destructiveHint is False
    assert ann["save_reviewed"].readOnlyHint is False
