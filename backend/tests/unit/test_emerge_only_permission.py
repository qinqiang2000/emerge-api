"""Coverage for the workspace-aware permission gate.

The previous incarnation of this test exercised an emerge-MCP-only allowlist —
that gate was retired in Step A of the agent tool-surface reframe. The gate
now classifies allow / deny / ask using path range-checks, secret-literal
sniffs, and a network-keyword heuristic.
"""
from pathlib import Path

import pytest

from app.chat.permissions import GateDecision, classify


# Reuse the conftest `workspace` fixture — it allocates a real on-disk root.


# ── emerge MCP allowlist (unchanged behaviour) ────────────────────────────


@pytest.mark.parametrize("name", [
    "mcp__emerge_tools__list_projects",
    "mcp__emerge_tools__write_schema",
    "mcp__emerge_tools__extract_batch",
])
def test_emerge_mcp_tools_always_allow(name: str, workspace: Path) -> None:
    decision = classify(name, {}, workspace_root=workspace)
    assert decision.behavior == "allow"


# ── foreign / never tools ─────────────────────────────────────────────────


@pytest.mark.parametrize("name", [
    "PowerShell",
    "mcp__claude_ai_Linear__authenticate",
    "mcp__plugin_chrome-devtools-mcp_chrome-devtools__click",
    "mcp__excalidraw__create_view",
])
def test_foreign_tools_deny(name: str, workspace: Path) -> None:
    decision = classify(name, {}, workspace_root=workspace)
    assert decision.behavior == "deny"


# ── Bash classification ───────────────────────────────────────────────────


def test_bash_inside_workspace_allows(workspace: Path) -> None:
    decision = classify(
        "Bash",
        {"command": f"ls {workspace}/some_project/docs/"},
        workspace_root=workspace,
    )
    assert decision.behavior == "allow"


def test_bash_network_keyword_asks(workspace: Path) -> None:
    decision = classify(
        "Bash",
        {"command": "curl https://example.com"},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


@pytest.mark.parametrize("cmd", [
    "wget https://example.com/x.tar.gz",
    "ssh user@host",
    "scp foo user@host:bar",
    "rsync -av src/ dst/host:/var/www/",
])
def test_bash_other_network_tools_ask(cmd: str, workspace: Path) -> None:
    decision = classify("Bash", {"command": cmd}, workspace_root=workspace)
    assert decision.behavior == "ask"


def test_bash_secret_literal_denies(workspace: Path) -> None:
    decision = classify(
        "Bash",
        {"command": f"echo $api_key > {workspace}/leak.txt"},
        workspace_root=workspace,
    )
    assert decision.behavior == "deny"


def test_bash_dotenv_target_denies(workspace: Path) -> None:
    decision = classify(
        "Bash",
        {"command": f"cat {workspace}/../backend/.env"},
        workspace_root=workspace,
    )
    assert decision.behavior == "deny"


def test_bash_out_of_workspace_asks(workspace: Path, tmp_path: Path) -> None:
    decision = classify(
        "Bash",
        {"command": f"ls {tmp_path}/somewhere_else"},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


def test_bash_ssh_key_path_denies(workspace: Path) -> None:
    decision = classify(
        "Bash",
        {"command": "cat ~/.ssh/id_rsa"},
        workspace_root=workspace,
    )
    assert decision.behavior == "deny"


# ── Read / Write / Edit / Glob / Grep ─────────────────────────────────────


def test_read_inside_workspace_allows(workspace: Path) -> None:
    decision = classify(
        "Read",
        {"file_path": str(workspace / "p1" / "docs" / "foo.pdf")},
        workspace_root=workspace,
    )
    assert decision.behavior == "allow"


def test_read_env_denies(workspace: Path) -> None:
    decision = classify(
        "Read",
        {"file_path": "/Users/anybody/project/backend/.env"},
        workspace_root=workspace,
    )
    assert decision.behavior == "deny"


def test_read_outside_workspace_asks(tmp_path: Path, workspace: Path) -> None:
    decision = classify(
        "Read",
        {"file_path": str(tmp_path / "other.txt")},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


def test_write_inside_workspace_allows(workspace: Path) -> None:
    decision = classify(
        "Write",
        {
            "file_path": str(workspace / "p1" / "prompts" / "scratch.json"),
            "content": "{}",
        },
        workspace_root=workspace,
    )
    assert decision.behavior == "allow"


def test_glob_no_path_allows(workspace: Path) -> None:
    decision = classify(
        "Glob",
        {"pattern": "**/*.py"},
        workspace_root=workspace,
    )
    assert decision.behavior == "allow"


def test_grep_outside_workspace_asks(workspace: Path, tmp_path: Path) -> None:
    decision = classify(
        "Grep",
        {"pattern": "TODO", "path": str(tmp_path / "elsewhere")},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


# ── WebFetch / WebSearch ──────────────────────────────────────────────────


def test_webfetch_asks(workspace: Path) -> None:
    decision = classify(
        "WebFetch",
        {"url": "https://example.com"},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


def test_websearch_asks(workspace: Path) -> None:
    decision = classify(
        "WebSearch",
        {"query": "claude agent sdk permissions"},
        workspace_root=workspace,
    )
    assert decision.behavior == "ask"


# ── Task / TodoWrite / Monitor / Cron* ────────────────────────────────────


@pytest.mark.parametrize("name", [
    "Task", "TaskCreate", "TaskUpdate", "TaskList",
    "TodoWrite", "Monitor", "CronCreate", "CronList",
])
def test_bookkeeping_tools_allow(name: str, workspace: Path) -> None:
    decision = classify(name, {}, workspace_root=workspace)
    assert decision.behavior == "allow"


# ── Unknown tools default to ask ──────────────────────────────────────────


def test_unknown_tool_asks(workspace: Path) -> None:
    decision = classify("SomethingNew", {}, workspace_root=workspace)
    assert decision.behavior == "ask"


# ── GateDecision is hashable / dataclass-equal (useful for tests) ─────────


def test_decision_equality() -> None:
    assert GateDecision("allow", "r") == GateDecision("allow", "r")
