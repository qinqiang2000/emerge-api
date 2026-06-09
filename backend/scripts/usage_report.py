#!/usr/bin/env python
"""Print the remote MCP tool-call distribution (per team, descending).

The headless connector logs every teammate tool call to ``_usage/calls.jsonl``
at the workspace root (see ``app/tools/usage.py``). This summarises it so P4
("keep which tools") is data-driven.

    cd backend && uv run python scripts/usage_report.py
    EMERGE_WORKSPACE_ROOT=/root/emerge/backend/workspace uv run python scripts/usage_report.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.usage import aggregate  # noqa: E402


def main() -> None:
    root = Path(os.environ.get("EMERGE_WORKSPACE_ROOT", "./workspace")).expanduser()
    data = aggregate(root)
    if not data:
        print(f"no usage recorded under {root}/_usage/calls.jsonl")
        return
    for team in sorted(data):
        counts = data[team]
        total = sum(counts.values())
        print(f"\n# team: {team}  ({total} calls, {len(counts)} distinct tools)")
        width = max(len(t) for t in counts)
        for tool, n in counts.items():  # already descending
            bar = "█" * min(40, n)
            print(f"  {tool.ljust(width)}  {str(n).rjust(5)}  {bar}")


if __name__ == "__main__":
    main()
