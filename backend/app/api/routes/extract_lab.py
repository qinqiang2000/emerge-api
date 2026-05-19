"""Lab-side HTTP for extract / extract-batch (M11 Phase B T10).

These routes mirror the `extract_one` and `extract_batch` tool surfaces so a
CLI agent driving HTTP can run extractions without going through chat. They
are explicitly *distinct* from the prod fast-path `POST /v1/extract` in
`publish.py`:

* Prod path takes a `published_id` form field, gates on `X-API-Key`, reads
  the *frozen* artifact at `_published/{pub_xxx}.json` (so its schema /
  model / params survive project rename or delete).
* Lab path is slug-scoped, uses session auth (none in dev — same as the
  rest of `/lab/*`), and runs through the project's *lab* state
  (active prompt's schema, active model). It writes back to
  `predictions/_draft/` exactly like the tool wrapper does.

Sharing the codepath: both ultimately reach `app.tools.extract`. The lab
route calls `extract_one` (which reads project state and persists the
draft prediction); the prod route calls `extract_bytes_with_schema` with
the frozen schema and no on-disk write. Different entry points, same
provider plumbing.

For batches with `len(filenames) > 8` we fire an in-route async task and
hand the caller a `j_xxx` job_id; status lands at the
`GET /lab/projects/{slug}/extract/batch/{job_id}` endpoint until the task
finishes. The autoresearch JobRunner is intentionally untouched — its
contract is per-skill, and `extract_batch` doesn't fit that mold yet.
This in-route tracker is the minimum viable async surface; if a third
async lab op shows up we promote it to a shared `JobRunner` skill.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes._safety import safe_filename, safe_slug
from app.config import get_settings
from app.tools.extract import extract_batch, extract_one
from app.workspace.ids import new_job_id
from app.workspace.paths import project_json_path


router = APIRouter()


# Threshold above which extract/batch flips from sync to async.
# 8 keeps simple "extract these 5 invoices" calls inline (no polling) while
# longer reviewed-set sweeps go async without blocking the HTTP request.
_BATCH_ASYNC_THRESHOLD = 8


# In-route async-job tracker. Lives at module level so the GET status route
# can read what the POST start route wrote. Single-process; lost on restart
# (matches M11 INSIGHTS #N stance on operational-vs-durable state — the
# durable record is the `predictions/_draft/` writes inside extract_one).
_BATCH_JOBS: dict[str, dict[str, Any]] = {}


def _project_or_404(slug: str) -> Path:
    safe_slug(slug)
    settings = get_settings()
    if not project_json_path(settings.workspace_root, slug).exists():
        raise HTTPException(
            status_code=404,
            detail={"error_code": "project_not_found"},
        )
    return settings.workspace_root


class _ExtractOneBody(BaseModel):
    """HTTP mirror of the `extract_one` tool input.

    `filename` is the on-disk doc handle (the only doc identifier post slug
    transparency). `prompt_id` / `model_id` are reserved hooks: the tool
    wrapper resolves both from the project's active state today, so we
    accept them for forward-compat but only `model_id` is plumbed through
    (the underlying `extract_one` takes an optional `model_id` already).
    A non-null `prompt_id` is currently a no-op and surfaces a 400 so
    callers don't silently assume per-call prompt switching is wired."""
    filename: str
    prompt_id: str | None = None
    model_id: str | None = None


@router.post("/lab/projects/{slug}/extract")
async def post_extract_one(slug: str, body: _ExtractOneBody) -> dict:
    """Extract a single document via the lab fast-path.

    Returns the prediction payload (`{entities: [...], _evidence: {...}}`)
    exactly as `extract_one` produces it — and as a side-effect persists
    the same payload to `predictions/_draft/{filename}.json` (so a follow-
    up `GET /lab/projects/{slug}/predictions/{filename}` reads the same
    blob without re-calling the model).

    Errors surface as structured 4xx envelopes:
    * 404 `project_not_found` — slug doesn't exist
    * 400 `invalid_filename` / `invalid_arg` — body validation
    * 400 `prompt_override_unsupported` — `prompt_id` is reserved
    * 404 `extract_failed` upstream errors bubble through unchanged
    """
    workspace = _project_or_404(slug)
    safe_filename(body.filename)
    if body.prompt_id is not None:
        # The tool surface doesn't expose per-call prompt override either —
        # callers should `switch_active_prompt` first. Surfacing this as
        # 400 keeps the wire contract honest.
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "prompt_override_unsupported",
                "error_message_en": (
                    "per-call prompt_id override is not supported; use "
                    "PUT /lab/projects/{slug}/prompts/active to switch first"
                ),
            },
        )
    try:
        payload = await extract_one(
            workspace, slug, body.filename, model_id=body.model_id or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "doc_not_found", "error_message_en": str(exc)},
        )
    except ValueError as exc:
        # Empty schema, etc. — surface validation reason.
        raise HTTPException(
            status_code=400,
            detail={"error_code": "invalid_arg", "error_message_en": str(exc)},
        )
    return payload


class _ExtractBatchBody(BaseModel):
    """HTTP mirror of the `extract_batch` tool input.

    `filenames` is required (empty list is treated as a no-op happy path
    rather than a 400 — matches what the tool returns for `[]`). The same
    forward-compat hooks as `_ExtractOneBody` apply.
    """
    filenames: list[str]
    prompt_id: str | None = None
    model_id: str | None = None


async def _run_batch(
    job_id: str,
    workspace: Path,
    slug: str,
    filenames: list[str],
    model_id: str | None,
) -> None:
    """Background task body for async batches.

    Catches every exception so a runtime failure shows up as `status=error`
    in the job slot rather than as an unhandled-task warning in the
    server log.
    """
    try:
        summary = await extract_batch(
            workspace, slug, filenames, model_id=model_id or None,
        )
        _BATCH_JOBS[job_id]["status"] = "done"
        _BATCH_JOBS[job_id]["result"] = summary
    except Exception as exc:  # noqa: BLE001
        _BATCH_JOBS[job_id]["status"] = "error"
        _BATCH_JOBS[job_id]["error"] = {
            "error_code": "extract_batch_failed",
            "error_message_en": str(exc),
        }
    finally:
        _BATCH_JOBS[job_id]["finished_at"] = time.time()


@router.post("/lab/projects/{slug}/extract/batch")
async def post_extract_batch(slug: str, body: _ExtractBatchBody) -> dict:
    """Extract a list of documents.

    Sync vs async split is purely a transport choice (the underlying
    `extract_batch` always runs the same concurrent gather):

    * `len(filenames) <= 8` — returns the full batch summary inline
      (`{ok_count, err_count, per_doc: {filename: {ok, entities|error}}}`).
    * `len(filenames) > 8` — returns `{job_id: "j_xxx"}` and fires the
      batch on a background task. Poll
      `GET /lab/projects/{slug}/extract/batch/{job_id}` for completion.
    """
    workspace = _project_or_404(slug)
    if body.prompt_id is not None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "prompt_override_unsupported",
                "error_message_en": (
                    "per-call prompt_id override is not supported; use "
                    "PUT /lab/projects/{slug}/prompts/active to switch first"
                ),
            },
        )
    for fn in body.filenames:
        safe_filename(fn)

    if len(body.filenames) <= _BATCH_ASYNC_THRESHOLD:
        try:
            summary = await extract_batch(
                workspace, slug, body.filenames, model_id=body.model_id or None,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "invalid_arg", "error_message_en": str(exc)},
            )
        return summary

    job_id = new_job_id()
    _BATCH_JOBS[job_id] = {
        "job_id": job_id,
        "slug": slug,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "n_filenames": len(body.filenames),
        "result": None,
        "error": None,
    }
    asyncio.create_task(
        _run_batch(job_id, workspace, slug, body.filenames, body.model_id),
        name=f"extract_batch:{job_id}",
    )
    return {"job_id": job_id, "status": "running"}


@router.get("/lab/projects/{slug}/extract/batch/{job_id}")
async def get_extract_batch_status(slug: str, job_id: str) -> dict:
    """Status / result for an async batch job.

    Returns the same `{status, result, error, ...}` envelope as the
    `start_job` job runner — flat enough that a CLI client can `jq`
    `.status` and `.result.ok_count` without indirection. The job slot
    lives in process memory; a backend restart loses pending status (the
    `predictions/_draft/` writes inside `extract_one` are still durable)."""
    safe_slug(slug)
    job = _BATCH_JOBS.get(job_id)
    if job is None or job.get("slug") != slug:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "job_not_found"},
        )
    return job
