"""Tests for headless interface signal —修正 1+2 从这里开始驱动。

Active context 注入 `interface: browser|headless`，skill prompts 包含
对应的渲染分支，MCP server 模块可导入。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.chat.service import ChatService, _UNBOUND_SLUG, _build_active_context
from app.provider.base import Provider
from app.tools.projects import create_project


def _make_svc(tmp_path: Path) -> ChatService:
    return ChatService(
        workspace=tmp_path,
        provider=AsyncMock(spec=Provider),
        agent_model="claude-sonnet-4-6",
    )


# ── Active context: interface signal ─────────────────────────────────────────


def test_active_context_browser_interface(tmp_path: Path) -> None:
    """Default call emits `interface: browser` in the Active context block."""
    block = _build_active_context(tmp_path, "ghost-slug", "c_test123")
    assert "interface: browser" in block


def test_active_context_headless_interface(tmp_path: Path) -> None:
    """`interface='headless'` emits `interface: headless`."""
    block = _build_active_context(tmp_path, "ghost-slug", "c_test123", interface="headless")
    assert "interface: headless" in block


def test_active_context_default_is_browser(tmp_path: Path) -> None:
    """Calling without interface= defaults to browser, not headless."""
    block = _build_active_context(tmp_path, "ghost-slug", "c_test123")
    assert "interface: headless" not in block


async def test_active_context_headless_with_real_project(workspace: Path) -> None:
    """Headless signal survives a real project.json read."""
    out = await create_project(workspace, name="テストプロジェクト")
    slug = out["slug"]
    block = _build_active_context(workspace, slug, "c_test123", interface="headless")
    assert "interface: headless" in block
    assert slug in block


def test_active_context_unbound_carries_interface(tmp_path: Path) -> None:
    """Unbound chat path also gets the interface signal."""
    block = _build_active_context(tmp_path, _UNBOUND_SLUG, "c_test123", interface="headless")
    assert "interface: headless" in block


# ── ChatService._build_system_prompt + chat_turn accept interface ─────────────


async def test_build_system_prompt_headless(workspace: Path) -> None:
    """_build_system_prompt forwards interface= into the active context block."""
    out = await create_project(workspace, name="receipt")
    slug = out["slug"]
    svc = _make_svc(workspace)
    prompt = svc._build_system_prompt(
        "extract", slug=slug, chat_id="c_test123", interface="headless",
    )
    assert "interface: headless" in prompt


async def test_build_system_prompt_default_browser(workspace: Path) -> None:
    """_build_system_prompt default produces interface: browser."""
    out = await create_project(workspace, name="invoice")
    slug = out["slug"]
    svc = _make_svc(workspace)
    prompt = svc._build_system_prompt("extract", slug=slug, chat_id="c_test123")
    assert "interface: browser" in prompt


def test_chat_turn_accepts_interface_param(tmp_path: Path) -> None:
    """chat_turn must accept interface= kwarg without TypeError."""
    import inspect
    from app.chat.service import ChatService
    sig = inspect.signature(ChatService.chat_turn)
    assert "interface" in sig.parameters, (
        "ChatService.chat_turn must accept `interface` keyword argument"
    )
    assert sig.parameters["interface"].default == "browser"


# ── Skill prompts: headless rendering branches ───────────────────────────────


def _load_skill(name: str) -> str:
    from app.skills import load_skill
    return load_skill(name)


def test_extractor_skill_has_headless_eval_rendering() -> None:
    """The /eval headless rendering contract lives in the experiments domain
    playbook (progressive disclosure, 2026-06-10); the always-on core still
    must carry the headless concept."""
    core = _load_skill("emerge_extractor")
    assert "headless" in core.lower(), "Core must mention headless rendering path"
    from app.skills import load_domain_skill
    exp = load_domain_skill("experiments")
    assert "markdown table" in exp.lower() or "| Field" in exp or "| field" in exp.lower()


def test_extractor_skill_ui_tools_headless_guidance() -> None:
    """emerge_extractor.md must tell the agent how to handle ui_* in headless."""
    skill = _load_skill("emerge_extractor")
    lower = skill.lower()
    # Must instruct agent to skip or narrate ui_* in headless
    assert "headless" in lower
    assert "ui_" in lower or "ui_goto_page" in lower or "narrat" in lower


def test_publish_skill_has_headless_readiness_rendering() -> None:
    """emerge_publish.md must describe headless rendering for readiness checklist."""
    skill = _load_skill("emerge_publish")
    assert "headless" in skill.lower()
    # Must have a checklist rendering instruction for headless
    assert "✅" in skill or "checklist" in skill.lower() or "check" in skill.lower()


def test_publish_skill_has_headless_api_key_guidance() -> None:
    """emerge_publish.md must tell the agent what to do with the API key in headless."""
    skill = _load_skill("emerge_publish")
    lower = skill.lower()
    assert "headless" in lower
    # Must reference the tool result for the key in headless
    assert "tool result" in lower or "plaintext" in lower


# ── MCP server module ─────────────────────────────────────────────────────────


def test_mcp_server_module_importable() -> None:
    """app.mcp_server must be importable (no top-level side-effects that fail)."""
    import importlib
    mod = importlib.import_module("app.mcp_server")
    assert hasattr(mod, "_main"), "mcp_server must expose `_main` coroutine"


def test_mcp_server_build_function_exists() -> None:
    """mcp_server must expose a `build_mcp_server` function for testing."""
    from app.mcp_server import build_mcp_server
    assert callable(build_mcp_server)


def test_mcp_server_excludes_ui_tools(tmp_path: Path) -> None:
    """The MCP server must not expose ui_* or ask_user tools."""
    from unittest.mock import MagicMock
    from app.mcp_server import build_mcp_server
    provider = MagicMock()
    job_runner = MagicMock()
    server = build_mcp_server(workspace=tmp_path, provider=provider, job_runner=job_runner)
    # server is the mcp.server.lowlevel.Server instance
    # We can't easily call list_tools synchronously, so check via the handler
    import asyncio
    from mcp.types import ListToolsRequest
    async def get_tools():
        handler = server.request_handlers.get(ListToolsRequest)
        if handler is None:
            return []
        result = await handler(ListToolsRequest(method="tools/list"))
        return [t.name for t in result.root.tools]
    tool_names = asyncio.run(get_tools())
    for excluded in ("ui_goto_page", "ui_set_active_field", "ui_set_active_tab",
                     "ui_set_active_entity", "ask_user"):
        assert excluded not in tool_names, f"{excluded} should be excluded from MCP server"
