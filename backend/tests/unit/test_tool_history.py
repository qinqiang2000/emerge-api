"""Agent-facing history tools (`app/tools/history.py`) over a real git repo.

Confirms the log/diff/restore impls scope by project, shape their returns for
the agent, and degrade to a clean error when a ref can't be restored. Skipped
when git is unavailable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.tools import history as history_tool
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
