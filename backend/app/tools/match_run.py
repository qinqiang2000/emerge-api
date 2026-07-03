"""`run_match` — execute a match project's reconcile and persist the result.

Reads the match project's references + active match prompt, resolves an L2
judge provider from the MATCH project's own active model (the design's "L2 judge
tier"), runs the engine, and writes `matches/{run_id}/result.json` (a derived
cache — re-running rebuilds it). Returns a compact summary.

Provider resolution is best-effort: if the match project has no usable active
model, the engine runs pure-L1 (deterministic) — matching still works, it just
can't escalate the ambiguous middle to an LLM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.match.engine import run_engine
from app.provider.base import Provider
from app.tools.match_project import read_match_project
from app.tools.match_prompt import read_active_match_prompt
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_match_run_id
from app.workspace.paths import match_result_path


async def _resolve_judge_provider(
    workspace: Path, slug: str,
) -> tuple[Optional[Provider], Optional[str]]:
    """Resolve (provider, model_id) for the L2 judge from the match project's
    own active model. Returns (None, None) if unresolvable — engine then runs
    pure-L1."""
    try:
        from app.provider import get_provider_for_model
        from app.tools.model import read_active_model

        mc = await read_active_model(workspace, slug)
        provider = get_provider_for_model(
            mc.provider_model_id, provider=mc.provider,
            base_url=mc.base_url, api_key_env=mc.api_key_env,
        )
        return provider, mc.provider_model_id
    except Exception:
        return None, None


async def run_match(
    workspace: Path,
    slug: str,
    *,
    provider: Optional[Provider] = None,
    model_id: Optional[str] = None,
) -> dict[str, Any]:
    """Run the match for project `slug`. `provider`/`model_id` override the
    resolved L2 judge (tests inject a mock here). Returns a summary dict with
    the run id + counts."""
    project = await read_match_project(workspace, slug)
    match_prompt = await read_active_match_prompt(workspace, slug)

    if provider is None:
        provider, resolved_model = await _resolve_judge_provider(workspace, slug)
        model_id = model_id or resolved_model

    run_id = new_match_run_id()
    result = await run_engine(
        workspace,
        run_id=run_id,
        anchor_project=project["anchor_project"],
        source_projects=project["source_projects"],
        match_prompt=match_prompt,
        provider=provider,
        model_id=model_id,
    )

    out_path = match_result_path(workspace, slug, run_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_path, result.model_dump(mode="json"))

    complete = sum(1 for c in result.cards if c.overall == "complete")
    partial = sum(1 for c in result.cards if c.overall == "partial")
    unmatched = sum(1 for c in result.cards if c.overall == "unmatched")
    orphan_count = sum(len(v) for v in result.orphans.values())
    return {
        "run_id": run_id,
        "anchor_project": result.anchor_project,
        "source_projects": result.source_projects,
        "cards": len(result.cards),
        "complete": complete,
        "partial": partial,
        "unmatched": unmatched,
        "orphans": orphan_count,
    }
