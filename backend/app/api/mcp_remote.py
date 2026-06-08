"""Remote (Streamable HTTP) MCP transport — emerge as a Claude *custom connector*.

Exposes the SAME business tools as the stdio ``app.mcp_server`` (Claude Code /
Desktop local) but over **Streamable HTTP**, so emerge works as a *remote
connector* in Claude Desktop / Cowork / claude.ai / mobile — no per-machine
setup, one central backend. This is the ``headless`` interface branch of the
rendering contract: the agent brain is the external Claude client; emerge
provides tools + the ``emerge-extractor`` skill prompt only (``ui_*`` /
``ask_user`` are filtered out by ``build_mcp_server``).

**Multi-tenant by request.** Every call is authenticated and routed to the
caller's team workspace — there is NO server-bound single team. Auth resolution
mirrors the rest of the app (``app.auth.deps``) plus one connector affordance:

  1. ``Authorization: Bearer <pat>``           (Claude Code / curl / headers)
  2. ``?token=<pat>`` / ``?k=<pat>`` query PAT  (paste a personal connector URL
     into Cowork/Desktop "Add custom connector" — no OAuth needed to onboard a
     teammate; see plan ``2026-06-08-cowork-remote-mcp.md`` phase P1)
  3. signed session cookie                      (browser)

One MCP ``Server`` is built + cached **per team workspace** (tools bake the
workspace ``Path`` at build time, exactly like the HTTP route layer — never a
hidden per-request global). Each manager's ``.run()`` task group lives in one
long-lived background task (anyio task groups can't be entered/exited across
tasks), gated by a stop ``Event`` — NOT in FastAPI's on_startup/on_shutdown
hooks, which run in different tasks.

Mounted at ``/mcp``. Opt out with ``EMERGE_MCP_REMOTE=0``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request

from app.auth import store
from app.auth.deps import _resolve_team_workspace, _unauthorized
from app.auth.models import User
from app.auth.tokens import verify_pat
from app.config import get_settings
from app.jobs import get_runner
from app.mcp_server import build_mcp_server
from app.provider import get_provider_for_model

log = logging.getLogger(__name__)


def remote_enabled() -> bool:
    """Remote MCP is on by default; ``EMERGE_MCP_REMOTE=0`` disables the mount.

    In tenant mode it is PAT-gated exactly like ``/lab/*``, so default-on does
    not widen the security posture; in open mode it is unauthenticated, matching
    the rest of the app in open mode.
    """
    return os.getenv("EMERGE_MCP_REMOTE", "1") != "0"


class _TeamMcp:
    __slots__ = ("manager", "stop", "task")

    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        stop: asyncio.Event,
        task: "asyncio.Task[None]",
    ) -> None:
        self.manager = manager
        self.stop = stop
        self.task = task


class RemoteMcpRegistry:
    """Lazily-built, cached ``StreamableHTTPSessionManager`` per team workspace.

    Construction is cheap (no provider / no I/O) so it is safe to instantiate in
    a startup hook even under test; the provider and per-team servers are built
    on first request to ``/mcp``.
    """

    def __init__(self) -> None:
        self._by_ws: dict[str, _TeamMcp] = {}
        self._lock = asyncio.Lock()
        self._provider: Any = None

    def _provider_for_extract(self) -> Any:
        if self._provider is None:
            self._provider = get_provider_for_model(
                get_settings().default_extract_model
            )
        return self._provider

    async def manager_for(self, workspace: Path) -> StreamableHTTPSessionManager:
        key = str(workspace)
        existing = self._by_ws.get(key)
        if existing is not None:
            return existing.manager
        async with self._lock:
            existing = self._by_ws.get(key)  # double-check under lock
            if existing is not None:
                return existing.manager
            provider = self._provider_for_extract()
            server = build_mcp_server(
                workspace=workspace,
                provider=provider,
                job_runner=get_runner(workspace=workspace, provider=provider),
            )
            manager = StreamableHTTPSessionManager(app=server, stateless=True)
            ready = asyncio.Event()
            stop = asyncio.Event()

            async def _serve() -> None:
                # The task group created by run() must be entered AND exited in
                # this single coroutine; we keep it open until stop is set.
                async with manager.run():
                    ready.set()
                    await stop.wait()

            task = asyncio.create_task(_serve(), name=f"mcp-remote:{key}")
            await ready.wait()
            self._by_ws[key] = _TeamMcp(manager, stop, task)
            log.info("remote MCP manager started for workspace %s", key)
            return manager

    async def shutdown(self) -> None:
        for tm in list(self._by_ws.values()):
            tm.stop.set()
        for tm in list(self._by_ws.values()):
            try:
                await tm.task
            except Exception:  # noqa: BLE001 — shutdown is best-effort
                pass
        self._by_ws.clear()


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, payload: dict) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _authenticate(req: Request) -> Path:
    """Resolve the caller's effective team workspace, or raise 401.

    Open mode (no users) → flat root, no auth. Tenant mode → header PAT, then
    query PAT, then session cookie; all three resolve to the same ``User`` and
    then to a team workspace via the shared ``_resolve_team_workspace``.
    """
    root = get_settings().workspace_root
    if not await store.auth_configured(root):
        return root  # open mode

    token: Optional[str] = None
    authz = req.headers.get("Authorization", "")
    if authz.startswith("Bearer "):
        token = authz[len("Bearer ") :].strip()
    if not token:
        token = req.query_params.get("token") or req.query_params.get("k")

    user: Optional[User] = None
    if token:
        uid = await verify_pat(root, token)
        if uid:
            user = await store.get_user(root, uid)
    if user is None:
        uid = req.scope.get("session", {}).get("uid") if req.scope.get("session") else None
        if uid:
            user = await store.get_user(root, uid)
    if user is None:
        raise _unauthorized()

    return await _resolve_team_workspace(req, user)


def make_mcp_asgi(get_registry: Callable[[], Optional[RemoteMcpRegistry]]):
    """Return an ASGI3 callable to mount at ``/mcp``.

    ``get_registry`` reads the process registry off ``app.state`` lazily (None
    when the feature is disabled or the startup hook has not run yet).
    """

    async def _app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await _send_json(send, 400, {
                "error_code": "bad_request",
                "error_message_en": "MCP endpoint is HTTP only",
            })
            return
        registry = get_registry()
        if registry is None:
            await _send_json(send, 404, {
                "error_code": "mcp_remote_disabled",
                "error_message_en": "remote MCP transport is not enabled",
            })
            return

        # Auth reads headers/query/cookie only — it never drains the body, so the
        # original `receive` is handed intact to the MCP transport below.
        from fastapi import HTTPException

        req = Request(scope, receive)
        try:
            workspace = await _authenticate(req)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            await _send_json(send, exc.status_code, {
                "error_code": detail.get("error_code", "unauthorized"),
                "error_message_en": detail.get("error_message_en", str(exc.detail)),
            })
            return

        manager = await registry.manager_for(workspace)
        await manager.handle_request(scope, receive, send)

    return _app
