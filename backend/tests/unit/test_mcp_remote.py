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
    server but NOT on the in-session chat server (which uses built-in Bash).
    Headless names carry the emerge_ service prefix."""
    discovery = {"emerge_list_projects", "emerge_list_docs", "emerge_read_prompt"}
    headless = await _server_tool_names(headless=True)
    chat = await _server_tool_names(headless=False)
    assert discovery <= headless, f"headless missing {discovery - headless}"
    bare = {n.removeprefix("emerge_") for n in discovery}
    assert not (bare & chat), f"chat server leaked discovery tools {bare & chat}"


async def _remote_surface_names() -> set[str]:
    """tools/list through build_mcp_server — the surface a remote client sees
    (headless build + _HEADLESS_EXCLUDE + EMERGE_MCP_SURFACE filter)."""
    from unittest.mock import AsyncMock

    from mcp.types import ListToolsRequest

    from app.mcp_server import build_mcp_server

    server = build_mcp_server(
        workspace=get_settings().workspace_root,
        provider=AsyncMock(), job_runner=AsyncMock(),
    )
    handler = server.request_handlers[ListToolsRequest]
    result = await handler(ListToolsRequest(method="tools/list"))
    return {t.name for t in result.root.tools}


async def test_minimal_surface_is_default(monkeypatch) -> None:
    """The minimal-surface experiment: default exposes the ws_* bus + invariant
    + LLM verbs only; pure read wrappers / setters / suites are unlisted."""
    names = await _remote_surface_names()
    assert {"emerge_ws_list", "emerge_ws_write", "emerge_ws_move",
            "emerge_add_model", "emerge_write_schema", "emerge_extract_one",
            "emerge_get_project_config"} <= names
    assert not ({"emerge_list_projects", "emerge_read_prompt", "emerge_bench_view",
                 "emerge_set_labeler_model", "emerge_run_audit"} & names)
    assert len(names) < 35, f"minimal surface grew to {len(names)}"


async def test_full_surface_via_env(monkeypatch) -> None:
    from app.config import get_settings as real_get_settings

    s = real_get_settings().model_copy(update={"mcp_surface": "full"})
    import app.config as config_mod
    monkeypatch.setattr(config_mod, "get_settings", lambda: s)
    names = await _remote_surface_names()
    assert {"emerge_list_projects", "emerge_read_prompt", "emerge_run_audit"} <= names
    assert len(names) > 50


async def test_headless_names_prefixed_chat_names_bare() -> None:
    """Every headless (remote/stdio) tool name carries the emerge_ service
    prefix (10+ connectors in one Cowork → bare names like create_project
    collide); the in-session chat surface stays bare (frontend matches tool
    names for cache invalidation)."""
    headless = await _server_tool_names(headless=True)
    chat = await _server_tool_names(headless=False)
    assert headless and all(n.startswith("emerge_") for n in headless), (
        sorted(n for n in headless if not n.startswith("emerge_")))
    assert chat and not any(n.startswith("emerge_") for n in chat), (
        sorted(n for n in chat if n.startswith("emerge_")))


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
    # annotations are stamped against bare names before the service prefix lands
    ann = {t.name.removeprefix("emerge_"): t.annotations for t in tools}

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
