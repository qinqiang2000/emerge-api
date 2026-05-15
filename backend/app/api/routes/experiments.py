from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.provider import get_provider_for_model
from app.tools.experiment import (
    ExperimentNotFoundError,
    extract_with_experiment,
    list_experiments,
    read_experiment,
)
from app.tools.model import read_model
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import experiment_prediction_path, project_json_path


router = APIRouter()


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{slug}/experiments")
async def get_project_experiments(
    slug: str,
    include_archived: bool = False,
) -> list[dict]:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    return await list_experiments(
        workspace, slug, include_archived=include_archived,
    )


@router.get("/lab/projects/{slug}/experiments/{experiment_id}")
async def get_project_experiment(slug: str, experiment_id: str) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        ex = await read_experiment(workspace, slug, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    return ex.model_dump(mode="json")


@router.get(
    "/lab/projects/{slug}/experiments/{experiment_id}/predictions/{filename:path}",
)
async def get_experiment_prediction(
    slug: str, experiment_id: str, filename: str,
) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    safe_filename(filename)
    try:
        await read_experiment(workspace, slug, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    p = experiment_prediction_path(workspace, slug, experiment_id, filename)
    if not p.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_prediction_not_found"},
        )
    return json.loads(p.read_text(encoding="utf-8"))


@router.post(
    "/lab/projects/{slug}/experiments/{experiment_id}/predictions/{filename:path}",
)
async def run_experiment_prediction(
    slug: str, experiment_id: str, filename: str,
) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    safe_filename(filename)
    try:
        ex = await read_experiment(workspace, slug, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    model = await read_model(workspace, slug, ex.model_id)
    provider = get_provider_for_model(model.provider_model_id, provider=model.provider)
    payload = await extract_with_experiment(
        workspace, slug, experiment_id, filename, provider=provider,
    )
    return payload
