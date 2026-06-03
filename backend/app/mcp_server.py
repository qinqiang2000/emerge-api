"""Standalone stdio MCP server for Claude Code / cowork integration.

Exposes all emerge business tools to an external agent (e.g. Claude Code)
without requiring the browser frontend. The agent brain is the external
Claude client; emerge provides tools only.

**Tools excluded** (browser side-channel, meaningless without a live viewer):
  ui_goto_page · ui_set_active_field · ui_set_active_tab ·
  ui_set_active_entity · ask_user

**Prompts exposed**:
  emerge-extractor  — the agent skill prompt (guides tool usage)

Usage
-----
Start the emerge FastAPI backend first, then add to ``~/.claude/settings.json``:

  {
    "mcpServers": {
      "emerge": {
        "command": "uv",
        "args": [
          "--project", "/absolute/path/to/emerge/backend",
          "run", "python", "-m", "app.mcp_server"
        ],
        "env": {
          "EMERGE_WORKSPACE": "/absolute/path/to/workspace"
        }
      }
    }
  }

Environment variables (same as the FastAPI backend):
  EMERGE_WORKSPACE          — workspace root dir (required)
  ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY
  EMERGE_DEFAULT_EXTRACT_MODEL / EMERGE_DEFAULT_AGENT_MODEL
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

# Load .env before importing app modules (mirrors app/main.py startup)
from dotenv import load_dotenv as _load_dotenv

_load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from mcp import stdio_server
from mcp.types import GetPromptRequest, GetPromptResult, ListPromptsRequest, Prompt, PromptMessage, TextContent

from app.config import get_settings
from app.jobs import get_runner
from app.provider import get_provider_for_model
from app.skills import load_skill
from app.tools import build_emerge_mcp

# Tools with no meaning outside of an active browser session.
# Mirrored from the _HTTP_EXEMPT rationale in test_symmetry_invariant.py.
_HEADLESS_EXCLUDE: frozenset[str] = frozenset({
    "ui_goto_page",
    "ui_set_active_field",
    "ui_set_active_tab",
    "ui_set_active_entity",
    # ask_user blocks on a chat-scoped asyncio future that an external caller
    # has no mechanism to resolve — it would deadlock.
    "ask_user",
})


def build_mcp_server(
    *,
    workspace: Path,
    provider: Any,
    job_runner: Any,
) -> Any:
    """Build and return a filtered ``mcp.server.lowlevel.Server`` instance.

    Wraps ``build_emerge_mcp()`` and:
    - Filters ``_HEADLESS_EXCLUDE`` tools from the list_tools response.
    - Registers the emerge-extractor skill as an MCP prompt so Claude Code
      can ``GET prompts/emerge-extractor`` to load the agent guidance.

    Returns the ``mcp.server.lowlevel.Server`` instance (``config["instance"]``).
    """
    from mcp.types import ListToolsRequest

    config = build_emerge_mcp(
        workspace=workspace,
        provider=provider,
        job_runner=job_runner,
    )
    server = config["instance"]

    # ── filter browser-only tools out of list_tools ───────────────────────
    _orig_list_tools = server.request_handlers[ListToolsRequest]

    async def _filtered_list_tools(req):  # type: ignore[override]
        result = await _orig_list_tools(req)
        result.root.tools = [
            t for t in result.root.tools if t.name not in _HEADLESS_EXCLUDE
        ]
        return result

    server.request_handlers[ListToolsRequest] = _filtered_list_tools

    # ── expose skill prompts as MCP prompts ───────────────────────────────
    _skill_text = load_skill("emerge_extractor")

    @server.list_prompts()
    async def _list_prompts() -> list[Prompt]:
        return [
            Prompt(
                name="emerge-extractor",
                description=(
                    "emerge-extractor agent skill — copy this into your system "
                    "prompt or /inject it to guide emerge tool usage "
                    "(workspace layout, discipline, slash commands, risk gates)."
                ),
            )
        ]

    @server.get_prompt()
    async def _get_prompt(name: str, arguments: dict[str, str] | None = None) -> GetPromptResult:
        if name == "emerge-extractor":
            return GetPromptResult(
                description="emerge-extractor agent skill",
                messages=[
                    PromptMessage(
                        role="user",
                        content=TextContent(type="text", text=_skill_text),
                    )
                ],
            )
        from mcp import McpError
        from mcp.types import ErrorData
        raise McpError(ErrorData(code=-32602, message=f"Unknown prompt: {name!r}"))

    return server


async def _main() -> None:
    """Entry point for stdio MCP server."""
    settings = get_settings()
    root = settings.workspace_root
    workspace = root
    # Multi-tenancy (2026-06-03): in tenant mode the stdio MCP must target one
    # team's workspace. `EMERGE_TEAM_ID` is the headless-cowork entry point
    # (Claude Desktop / Claude Code mounting emerge as an MCP server) for
    # picking the tenant — without it we can't know which team's projects to
    # serve. Open mode (no users yet) keeps the flat root, as before.
    from app.auth import store as _auth_store
    from app.workspace.paths import team_workspace_dir

    if await _auth_store.auth_configured(root):
        team_id = os.environ.get("EMERGE_TEAM_ID", "").strip()
        if not team_id:
            raise SystemExit(
                "error: tenant mode is ON — set EMERGE_TEAM_ID to the team whose "
                "workspace this MCP server should serve"
            )
        workspace = team_workspace_dir(root, team_id)
    provider = get_provider_for_model(settings.default_extract_model)
    job_runner = get_runner(workspace=workspace, provider=provider)

    server = build_mcp_server(
        workspace=workspace,
        provider=provider,
        job_runner=job_runner,
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_main())
