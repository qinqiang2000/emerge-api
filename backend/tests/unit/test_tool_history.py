"""Agent-facing history tools (`app/tools/history.py`) over a real git repo.

Confirms the log/diff/restore impls scope by project, shape their returns for
the agent, and degrade to a clean error when a ref can't be restored. Skipped
when git is unavailable.

P4 Task 11 adds a second layer below: the MCP *tool* surface, where
`history_log` + `history_diff` fold into `history(op=)` (both read-only) while
`history_restore` stays its own tool (it mutates — "same policy" is one of the
four merge criteria, and folding a mutating op in would let it inherit a
read-only annotation, exactly what that criterion exists to block). The impls
above are untouched by that merge — only the `@tool` wrappers in
`app/tools/__init__.py` changed — so those tests keep calling
`history_tool.history_log` etc. directly; the new ones below go through the
actual MCP dispatch to pin the tool-surface contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.tools import _READ_ONLY, build_emerge_mcp, history as history_tool, registered_tool_names
from app.workspace import history as history_lib

pytestmark = pytest.mark.skipif(not history_lib.git_available(), reason="git not on PATH")


def _commit(ws: Path, rel: str, text: str, msg: str) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    sha = history_lib.commit_all(ws, msg)
    assert sha
    return sha


async def test_history_log_scopes_by_project(workspace: Path) -> None:
    history_lib.ensure_repo(workspace)
    _commit(workspace, "alpha/project.json", "{}", "alpha created")
    _commit(workspace, "beta/project.json", "{}", "beta created")

    full = await history_tool.history_log(workspace)
    assert full["scope"] == "workspace"
    assert {v["message"] for v in full["versions"]} >= {"alpha created", "beta created"}

    scoped = await history_tool.history_log(workspace, slug="alpha")
    msgs = {v["message"] for v in scoped["versions"]}
    assert "alpha created" in msgs and "beta created" not in msgs
    # each version carries an agent-renderable ref + date
    assert all({"ref", "date", "message"} <= v.keys() for v in scoped["versions"])


async def test_history_diff_between_versions(workspace: Path) -> None:
    history_lib.ensure_repo(workspace)
    v1 = _commit(workspace, "p/global_notes.md", "old\n", "v1")
    v2 = _commit(workspace, "p/global_notes.md", "new\n", "v2")

    out = await history_tool.history_diff(workspace, ref_a=v1, ref_b=v2, slug="p")
    assert out["scope"] == "p"
    assert "-old" in out["diff"] and "+new" in out["diff"]
    assert out["truncated"] is False


async def test_history_restore_round_trips(workspace: Path) -> None:
    history_lib.ensure_repo(workspace)
    v1 = _commit(workspace, "p/schema.json", '{"v": 1}', "v1")
    _commit(workspace, "p/schema.json", '{"v": 2}', "v2")

    out = await history_tool.history_restore(workspace, ref=v1, slug="p")
    assert out["ok"] is True
    assert out["scope"] == "p"
    assert (workspace / "p" / "schema.json").read_text() == '{"v": 1}'
    # restore minted a new version on top
    log = await history_tool.history_log(workspace, slug="p")
    assert any("restore" in v["message"] for v in log["versions"])


async def test_history_restore_unknown_ref_errors_cleanly(workspace: Path) -> None:
    history_lib.ensure_repo(workspace)
    _commit(workspace, "p/x", "1", "v1")
    out = await history_tool.history_restore(workspace, ref="deadbeef", slug="p")
    assert out["ok"] is False
    assert out["error"]["error_code"] == "restore_failed"


# ---------------------------------------------------------------------------
# MCP tool surface — history(op=) (P4 Task 11)
# ---------------------------------------------------------------------------


async def _call(server, name: str, args: dict):
    from mcp.types import CallToolRequest, CallToolRequestParams

    handler = server["instance"].request_handlers[CallToolRequest]
    return await handler(
        CallToolRequest(
            method="tools/call",
            params=CallToolRequestParams(name=name, arguments=args),
        )
    )


async def test_history_log_lists_versions(workspace: Path, stub_provider) -> None:
    """Copy of the assertions in test_history_routes.py::
    test_history_routes_log_diff_restore's `log` section, driven through the
    tool dispatch instead of HTTP."""
    history_lib.ensure_repo(workspace)
    _commit(workspace, "p/global_notes.md", "v1\n", "v1")
    _commit(workspace, "p/global_notes.md", "v2\n", "v2")

    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "history", {"op": "log", "slug": "p"})
    out = json.loads(res.root.content[0].text)
    msgs = {v["message"] for v in out["versions"]}
    assert {"v1", "v2"} <= msgs


async def test_history_diff_returns_a_field_delta(workspace: Path, stub_provider) -> None:
    """Copy of the `diff` section of the same route test."""
    history_lib.ensure_repo(workspace)
    notes = workspace / "p" / "global_notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text("old\n", encoding="utf-8")
    v1 = history_lib.commit_all(workspace, "v1")
    notes.write_text("new\n", encoding="utf-8")
    history_lib.commit_all(workspace, "v2")

    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "history", {"op": "diff", "a": v1, "slug": "p"})
    out = json.loads(res.root.content[0].text)
    assert "+new" in out["diff"]


async def test_history_diff_without_a_is_a_clean_error(
    workspace: Path, stub_provider,
) -> None:
    """`a` is required only when `op='diff'` — a cross-parameter constraint
    flat JSON Schema can't express (see "jsonschema 在 handler 之前跑" in the
    plan doc), so unlike the enum/required guards elsewhere in this P4 pass,
    this ONE guard is real: it is reachable and this is the test that proves
    it, not a dead branch."""
    history_lib.ensure_repo(workspace)
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    res = await _call(server, "history", {"op": "diff", "slug": "p"})
    text = res.root.content[0].text
    assert "history_diff_requires_a" in text


def test_history_restore_stays_separate() -> None:
    live = registered_tool_names(headless=True)
    assert "history" in live
    assert "history_restore" in live, "restore mutates — must not be folded in"
    assert "history_log" not in live
    assert "history_diff" not in live
    assert "history" in _READ_ONLY
    assert "history_restore" not in _READ_ONLY
