"""Bench leaderboard MCP tool — thin delegate to compute_bench.

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T3.

`bench_view(workspace, project_id)` is the MCP-tool counterpart to
the `GET /lab/projects/{slug}/bench` HTTP route — both delegate to
`app.services.bench.compute_bench` so the in-session agent and a
CLI client driving HTTP see identical leaderboard output.

The service applies its own defensive `_validate_project_id` gate,
so this wrapper stays a pure pass-through (no extra validation).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.bench import compute_bench


async def bench_view(workspace: Path, project_id: str) -> dict[str, Any]:
    """Return the bench leaderboard for one project. See
    `compute_bench` for the response shape."""
    return compute_bench(workspace, project_id)
