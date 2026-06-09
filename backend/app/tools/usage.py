"""Remote MCP tool-call usage log — turns "let the plugin run a while" into
data for P4 (tool convergence).

The remote connector exposes ~40+ tools; deciding which to keep / collapse for
non-technical teammates should be driven by what they *actually* call, not a
guess. ``build_emerge_mcp(headless=True)`` wraps each tool handler so every
remote/stdio call appends one line here — emerge's own browser chat
(``headless=False``) is NOT logged (that's the operator, not a teammate).

Storage: append-only JSONL at the TRUE root ``_usage/calls.jsonl``. A single
short line append is atomic on POSIX (< PIPE_BUF), so no lock is needed even
under concurrent teammates. This is **derived telemetry, not user data** — safe
to wipe; it carries only ``{ts, team, tool}`` (no args, no document content).

Recording is strictly best-effort: a logging failure must never break a tool
call, so everything is wrapped in a bare except.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.workspace.paths import usage_log_path


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def record_tool_call(workspace: Path, tool_name: str) -> None:
    """Append one usage line for a tool call in `workspace` (a team dir).
    Best-effort: never raises."""
    try:
        root = get_settings().workspace_root
        path = usage_log_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"ts": _iso_now(), "team": workspace.name, "tool": tool_name},
            ensure_ascii=False,
        ) + "\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass  # telemetry must never break a tool call


def wrap_handler(handler, workspace: Path, tool_name: str):
    """Return an async handler that records the call then delegates. Used by
    `build_emerge_mcp` on the headless surface only."""

    async def _logged(args: dict):
        record_tool_call(workspace, tool_name)
        return await handler(args)

    return _logged


def aggregate(root: Path) -> dict[str, dict[str, int]]:
    """Read the log into `{team: {tool: count}}` (counts descending per team).
    Tolerant of partial/corrupt lines."""
    path = usage_log_path(root)
    if not path.exists():
        return {}
    per_team: dict[str, Counter] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            team, tool = rec["team"], rec["tool"]
        except Exception:
            continue
        per_team.setdefault(team, Counter())[tool] += 1
    return {team: dict(c.most_common()) for team, c in per_team.items()}
