"""HTTP routes for project LLM-role config — the `/config` surface.

Thin-delegate mirror of the MCP tools (`get_project_config`,
`set_translate_model`, `set_proposer_model`) so a CLI agent or non-Claude
client can inspect and tune the same per-project model roles over plain HTTP
([[feedback_ai_native_api_symmetry]]). Selection-only: no secrets/keys cross
this boundary. extract + labeler already have their own routes
(`models.py`, `label_docs.py`); this fills in the two missing setters plus the
aggregate read.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.routes._safety import safe_slug
from app.auth.deps import bind_workspace, current_ws
from app.jobs.autoresearch import set_proposer_model
from app.tools.project_config import get_project_config
from app.tools.translate import set_translate_model
from app.workspace.paths import project_json_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    if not project_json_path(current_ws(), slug).exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "project_not_found"},
        )
    return current_ws()


@router.get("/lab/projects/{slug}/config")
async def get_config(slug: str) -> dict:
    """Aggregate the four tunable LLM roles + active prompt for this project.

    Mirrors the `get_project_config` tool — the agent and a curl-based debug
    session see the identical {extract, labeler, proposer, translate,
    agent_brain} snapshot."""
    workspace = _project_or_404(slug)
    return await get_project_config(workspace, slug)


class _ModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str


@router.put("/lab/projects/{slug}/translate_model")
async def put_translate_model(slug: str, body: _ModelBody) -> dict:
    workspace = _project_or_404(slug)
    await set_translate_model(workspace, slug, body.model_id)
    return {"ok": True}


@router.put("/lab/projects/{slug}/proposer_model")
async def put_proposer_model(slug: str, body: _ModelBody) -> dict:
    workspace = _project_or_404(slug)
    await set_proposer_model(workspace, slug, body.model_id)
    return {"ok": True}
