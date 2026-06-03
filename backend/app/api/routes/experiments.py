from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.provider import get_provider_for_model
from app.tools.experiment import (
    ExperimentInUseError,
    ExperimentNotFoundError,
    archive_experiment,
    create_experiment,
    extract_with_experiment,
    list_experiments,
    promote_experiment,
    read_experiment,
    run_experiment_eval,
)
from app.tools.ground import ground_entities, has_evidence
from app.tools.model import ModelNotFoundError, read_model
from app.tools.prompt import PromptNotFoundError
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import experiment_prediction_path, project_json_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(current_ws(), slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return current_ws()


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


class _GroundExperimentBody(BaseModel):
    """Re-ground an experiment prediction's EXISTING entities (no re-extract).
    `force` re-runs even when the blob already carries evidence."""
    force: bool = False


@router.post(
    "/lab/projects/{slug}/experiments/{experiment_id}/predictions/{filename:path}/ground",
)
async def ground_experiment_prediction(
    slug: str, experiment_id: str, filename: str,
    body: _GroundExperimentBody | None = None,
) -> dict:
    """Render-support: ground an experiment prediction's ALREADY-extracted
    entities → per-field ``{page, source}`` evidence, cached back into the blob.

    Distinct from ``POST .../predictions/{filename}`` (which RE-EXTRACTS — double
    LLM call, mutates entities, slow enough to time the client out): this runs
    only the single grounding pass over the existing entities and never touches
    them. It is the experiment-tab analogue of ``/ground`` (whose ``_blob_path``
    covers ``_draft``/``_pending`` only), letting un-grounded experiment blobs
    catch up to the eager produce-time grounding without a re-extract.

    Registered BEFORE ``run_experiment_prediction`` because that route's greedy
    ``{filename:path}`` would otherwise swallow the ``/ground`` suffix.

    NOT a @tool — like ``/ground`` and ``/locate`` it backs the review render
    layer only (output is page + verbatim quote, NEVER coordinates). The symmetry
    invariant enforces "@tool ⇒ route"; a route with no tool is legitimate and
    needs no exempt entry. See app/api/routes/ground.py header + INSIGHTS.md #7.
    """
    body = body or _GroundExperimentBody()
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
    path = experiment_prediction_path(workspace, slug, experiment_id, filename)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_prediction_not_found"},
        )
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not body.force and has_evidence(blob):
        return {"evidence": blob.get("_evidence") or []}
    entities = blob.get("entities") or []
    if not entities:
        return {"evidence": []}

    try:
        model = await read_model(workspace, slug, ex.model_id)
    except ModelNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found", "error_message_en": str(exc)},
        )
    provider = get_provider_for_model(model.provider_model_id, provider=model.provider)
    try:
        evidence = await ground_entities(
            workspace, slug, filename, entities,
            provider=provider, model_id=model.provider_model_id,
        )
    except Exception as exc:  # noqa: BLE001 — provider failure envelope
        # Mirror the /ground route: a transient upstream blip (振兴 proxy →
        # httpx.ConnectError) returns a structured 503 with `transient`, not a
        # raw 500, so a retry-capable client knows to re-run.
        from app.provider.retry import is_transient

        transient = is_transient(exc)
        raise HTTPException(
            status_code=503 if transient else 502,
            detail={
                "error_code": (
                    "ground_provider_unavailable" if transient
                    else "ground_provider_failed"
                ),
                "error_message_en": str(exc) or type(exc).__name__,
                "transient": transient,
            },
        ) from exc

    # Write evidence back under the project lock: re-read so a concurrent save
    # isn't clobbered, and only stamp when the entity count still lines up
    # (mirror ground_prediction's write guard).
    async with project_lock(workspace, slug):
        current = json.loads(path.read_text(encoding="utf-8"))
        if len(current.get("entities") or []) == len(entities):
            current["_evidence"] = evidence
            atomic_write_json(path, current)
    return {"evidence": evidence}


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
    try:
        payload = await extract_with_experiment(
            workspace, slug, experiment_id, filename, provider=provider,
        )
    except Exception as exc:  # noqa: BLE001 — provider failure envelope
        # Mirror the t_extract_with_experiment tool envelope so a CLI agent
        # driving HTTP gets the same transient-vs-permanent signal instead of
        # an opaque 500. Transient = flaky upstream (re-run the doc).
        from app.provider.retry import is_transient

        transient = is_transient(exc)
        raise HTTPException(
            status_code=503 if transient else 502,
            detail={
                "error_code": (
                    "extract_provider_unavailable" if transient
                    else "extract_provider_failed"
                ),
                "error_message_en": str(exc) or type(exc).__name__,
                "transient": transient,
            },
        )
    return payload


# ---------------------------------------------------------------------------
# M11 T12: HTTP setters mirroring the t_create_experiment / t_run_experiment_eval
# / t_promote_experiment tool surfaces. Each route is a thin delegate to the
# same module function the tool wraps — no business logic lives here.
# ---------------------------------------------------------------------------


class _CreateExperimentBody(BaseModel):
    """Both axes default to the project's active. Mirrors the
    `create_experiment` tool's input schema: upsert by (prompt, model)."""
    prompt_id: str | None = None
    model_id: str | None = None


@router.post("/lab/projects/{slug}/experiments")
async def post_create_experiment(slug: str, body: _CreateExperimentBody) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        eid = await create_experiment(
            workspace, slug,
            prompt_id=body.prompt_id or None,
            model_id=body.model_id or None,
        )
    except PromptNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "prompt_not_found", "error_message_en": str(exc)},
        )
    except ModelNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found", "error_message_en": str(exc)},
        )
    except ValueError as exc:
        # `_resolve_active_{prompt,model}_id` raises ValueError when the
        # project lacks an active axis. Surface as 400 so callers see the
        # validation reason instead of a generic 500.
        raise HTTPException(
            status_code=400,
            detail={"error_code": "active_axis_missing", "error_message_en": str(exc)},
        )
    ex = await read_experiment(workspace, slug, eid)
    return ex.model_dump(mode="json")


class _RunEvalBody(BaseModel):
    """`run_experiment_eval` walks all `reviewed/` docs. `filenames` is
    reserved for a future scoped-eval variant. `use_llm_judge` opts in the
    L2 LLM-as-judge layer. Empty body is valid."""
    filenames: list[str] | None = None
    use_llm_judge: bool = False


@router.post("/lab/projects/{slug}/experiments/{experiment_id}/eval")
async def post_run_experiment_eval(
    slug: str, experiment_id: str, body: _RunEvalBody | None = None,
) -> dict:
    """Synchronous eval — loops every `reviewed/` doc through the experiment's
    (prompt, model). May take a while for large reviewed sets; the symmetric
    long-running form is the `start_job(skill='autoresearch')` background path
    (mirrored by `/lab/jobs/*` routes). Keeping this endpoint sync matches the
    `t_run_experiment_eval` tool semantics so a CLI client can invoke eval the
    same way the in-session agent does."""
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    try:
        ex = await read_experiment(workspace, slug, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    try:
        model = await read_model(workspace, slug, ex.model_id)
    except ModelNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "model_not_found", "error_message_en": str(exc)},
        )
    provider = get_provider_for_model(model.provider_model_id, provider=model.provider)
    try:
        ev = await run_experiment_eval(
            workspace, slug, experiment_id, provider=provider,
            use_llm_judge=(body.use_llm_judge if body is not None else False),
        )
    except ExperimentInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "experiment_promoted", "error_message_en": str(exc)},
        )
    except ValueError as exc:
        # No reviewed docs to score against.
        raise HTTPException(
            status_code=400,
            detail={"error_code": "no_reviewed_docs", "error_message_en": str(exc)},
        )
    return ev


class _PromoteExperimentBody(BaseModel):
    """`to='active'` flips the project's active (prompt, model) to this
    experiment's pair and re-seeds `predictions/_draft/`. `to='archived'`
    soft-archives the experiment (blocked on `status='promoted'` per audit
    trail)."""
    to: Literal["active", "archived"] = "active"


@router.post("/lab/projects/{slug}/experiments/{experiment_id}/promote")
async def post_promote_experiment(
    slug: str, experiment_id: str, body: _PromoteExperimentBody | None = None,
) -> dict:
    workspace = _project_or_404(slug)
    await migrate_project_if_needed(workspace, slug)
    target = (body.to if body is not None else "active")
    try:
        await read_experiment(workspace, slug, experiment_id)
    except ExperimentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "experiment_not_found"},
        )
    try:
        if target == "archived":
            await archive_experiment(workspace, slug, experiment_id)
        else:
            await promote_experiment(workspace, slug, experiment_id)
    except ExperimentInUseError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error_code": "experiment_promoted", "error_message_en": str(exc)},
        )
    return {"ok": True}
