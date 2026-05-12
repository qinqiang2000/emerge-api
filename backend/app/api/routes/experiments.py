from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.api.routes._safety import safe_project_id
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
from app.workspace.paths import experiment_extract_path, project_json_path


router = APIRouter()


def _project_or_404(pid: str) -> Path:
    safe_project_id(pid)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, pid).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


@router.get("/lab/projects/{project_id}/experiments")
async def get_project_experiments(
    project_id: str,
    include_archived: bool = False,
) -> list[dict]:
    workspace = _project_or_404(project_id)
    await migrate_project_if_needed(workspace, project_id)
    return await list_experiments(
        workspace, project_id, include_archived=include_archived,
    )


@router.get("/lab/projects/{project_id}/experiments/{experiment_id}")
async def get_project_experiment(project_id: str, experiment_id: str) -> dict:
    workspace = _project_or_404(project_id)
    try:
        ex = await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    return ex.model_dump(mode="json")


@router.get(
    "/lab/projects/{project_id}/experiments/{experiment_id}/extracts/{doc_id}",
)
async def get_experiment_extract(
    project_id: str, experiment_id: str, doc_id: str,
) -> dict:
    workspace = _project_or_404(project_id)
    try:
        await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    p = experiment_extract_path(workspace, project_id, experiment_id, doc_id)
    if not p.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_extract_not_found"},
        )
    return json.loads(p.read_text(encoding="utf-8"))


@router.post(
    "/lab/projects/{project_id}/experiments/{experiment_id}/extracts/{doc_id}",
)
async def run_experiment_extract(
    project_id: str, experiment_id: str, doc_id: str,
) -> dict:
    workspace = _project_or_404(project_id)
    try:
        ex = await read_experiment(workspace, project_id, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    model = await read_model(workspace, project_id, ex.model_id)
    provider = get_provider_for_model(model.provider_model_id)
    payload = await extract_with_experiment(
        workspace, project_id, experiment_id, doc_id, provider=provider,
    )
    return payload
