"""Bench leaderboard HTTP surface — thin delegate to compute_bench.

Plan: docs/superpowers/plans/2026-05-28-bench-leaderboard.md §T3.

`GET /lab/projects/{slug}/bench` returns the project's bench
leaderboard (one row per non-archived experiment + a synthetic
baseline row when a baseline eval exists on disk). The entire
aggregation lives in `app.services.bench.compute_bench` so this
route and the symmetric `bench_view` MCP tool produce identical
output for the same project.

`safe_slug` is invoked first so attacker-supplied slugs (NUL,
`..`, slashes) get rejected with a 400 before any filesystem read,
per INSIGHTS #8.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.services.bench import compute_bench
from app.workspace.paths import project_json_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


@router.get("/lab/projects/{slug}/bench")
async def get_bench(slug: str) -> dict:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(current_ws(), slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return compute_bench(current_ws(), slug)
