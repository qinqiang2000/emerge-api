"""HTTP routes for the Pro Labeler.

Thin-delegate mirror of the MCP tools (`label_docs`, `set_labeler_model`,
`get_labeler_config`) so a CLI agent or non-Claude client can drive the same
pre-label flow over plain HTTP.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.routes._safety import safe_slug
from app.config import get_settings
from app.tools.pre_label import (
    LabelerNotConfiguredError,
    get_labeler_config,
    label_docs,
    set_labeler_model,
)
from app.workspace.paths import project_json_path


router = APIRouter()


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(
            status_code=404, detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


class _LabelDocsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filenames: Optional[list[str]] = None
    labeler_model: Optional[str] = None


@router.post("/lab/projects/{slug}/label_docs")
async def post_label_docs(slug: str, body: _LabelDocsBody) -> dict:
    """Run the Pro-labeler synchronously over `filenames` (or all unreviewed
    docs when omitted). Returns the standard `{processed, skipped, errors,
    labeler_model}` envelope. Maps `LabelerNotConfiguredError → 400` with
    error_code `labeler_model_not_configured` so the frontend can surface a
    clear "configure a labeler first" affordance."""
    workspace = _project_or_404(slug)
    try:
        return await label_docs(
            workspace, slug,
            filenames=body.filenames,
            labeler_model=body.labeler_model,
        )
    except LabelerNotConfiguredError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "labeler_model_not_configured",
                "error_message_en": str(e),
            },
        )


class _LabelerModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str


@router.post("/lab/projects/{slug}/labeler_model")
async def post_labeler_model(slug: str, body: _LabelerModelBody) -> dict:
    workspace = _project_or_404(slug)
    await set_labeler_model(workspace, slug, body.model_id)
    return {"ok": True}


@router.get("/lab/projects/{slug}/labeler_config")
async def get_labeler_config_route(slug: str) -> dict:
    """Report `{override, env_default, resolved, source}` so a CLI agent (or
    a curl-based debug session) can see what `label_docs` will actually call
    without parsing `project.json` and missing the env fallback."""
    workspace = _project_or_404(slug)
    return await get_labeler_config(workspace, slug)
