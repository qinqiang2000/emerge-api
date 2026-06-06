"""Project-level LLM-role config aggregator — powers `/config`.

emerge runs five LLM axes (see CLAUDE.md 五层 LLM). Four are project-tunable
and live as keys in `project.json`; the agent-brain is locked at the system
level. This module gathers all four into one snapshot so the agent can answer
"你现在怎么配置的" without `Read`ing `project.json` (which misses env
fallbacks — see [[feedback_ai_native_api_symmetry]]).

Read-only aggregation: each role's resolution lives next to its reader
(`pre_label.get_labeler_config`, `translate.get_translate_config`,
`autoresearch.get_proposer_config`); we only stitch them together here. The
autoresearch import is function-local to avoid an import cycle
(`jobs.autoresearch` pulls `app.tools.*` at module load).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.model import ModelNotFoundError, read_active_model
from app.tools.pre_label import get_labeler_config
from app.tools.translate import get_translate_config
from app.workspace.paths import project_json_path


async def get_project_config(workspace: Path, slug: str) -> dict[str, Any]:
    """Aggregate the four tunable LLM roles + active prompt for this project.

    Returns a dict with `active_prompt_id`, `extract` (the live active model
    triple, or None if unresolved), `labeler` / `proposer` / `translate`
    (each a `{override, resolved, source, …}` snapshot from its own reader),
    and `agent_brain` (locked marker). Secrets / provider keys never appear —
    this surface is model-selection only.
    """
    # Lazy import: jobs.autoresearch imports app.tools.* at module load, so a
    # top-level import here can race the tools package __init__.
    from app.jobs.autoresearch import get_proposer_config

    pj = project_json_path(workspace, slug)
    active_prompt_id: str | None = None
    if pj.exists():
        try:
            blob = json.loads(pj.read_text(encoding="utf-8"))
            active_prompt_id = blob.get("active_prompt_id") or None
        except (OSError, json.JSONDecodeError):
            pass

    try:
        mc = await read_active_model(workspace, slug)
        extract: dict[str, Any] | None = {
            "model_id": mc.model_id,
            "label": mc.label,
            "provider": mc.provider,
            "provider_model_id": mc.provider_model_id,
        }
    except ModelNotFoundError:
        extract = None

    return {
        "active_prompt_id": active_prompt_id,
        "extract": extract,
        "labeler": await get_labeler_config(workspace, slug),
        "proposer": await get_proposer_config(workspace, slug),
        "translate": await get_translate_config(workspace, slug),
        "agent_brain": {
            "locked": True,
            "note": "system-level (Anthropic); not project-tunable",
        },
    }
