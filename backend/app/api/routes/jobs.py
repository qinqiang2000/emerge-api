from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.deps import bind_workspace, current_ws
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.routes._safety import safe_job_id, safe_slug
from app.config import get_settings
from app.jobs import get_runner
from app.jobs.runner import JobNotFoundError, UnknownSkillError
from app.provider import get_provider_for_model
from app.workspace.paths import job_log_path


router = APIRouter(dependencies=[Depends(bind_workspace)])


class StartJobBody(BaseModel):
    skill: str
    # Field name retained for FE back-compat; the value is now a slug (folder
    # handle). The runner's `project_id` kwarg likewise carries the slug —
    # paths are slug-keyed end-to-end.
    project_id: str
    params: dict[str, Any] = {}


def _get_runner():
    settings = get_settings()
    provider = get_provider_for_model(settings.default_extract_model)
    return get_runner(workspace=current_ws(), provider=provider)


@router.post("/lab/jobs")
async def start_job(body: StartJobBody) -> dict:
    safe_slug(body.project_id)
    runner = _get_runner()
    try:
        jid = await runner.start(skill=body.skill, project_id=body.project_id, params=body.params)
    except UnknownSkillError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "unknown_skill", "error_message_en": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "invalid_request", "error_message_en": str(exc)})
    return {"job_id": jid}


@router.get("/lab/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        info = await runner.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return info.model_dump(mode="json")


@router.post("/lab/jobs/{job_id}/pause")
async def post_pause(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.pause(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.post("/lab/jobs/{job_id}/resume")
async def post_resume(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.resume(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.post("/lab/jobs/{job_id}/cancel")
async def post_cancel(job_id: str) -> dict:
    safe_job_id(job_id)
    runner = _get_runner()
    try:
        await runner.cancel(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"error_code": "job_not_found"})
    return {"ok": True}


@router.get("/lab/jobs/{job_id}/events")
async def get_job_events(
    job_id: str,
    project_id: str = Query(...),
) -> EventSourceResponse:
    """Tail the job's JSONL file as SSE. Backfills existing events on connect,
    then watches for new lines via 200ms poll. Closes when an `ended` event
    is observed.

    `project_id` query param value is a slug (folder handle) — kept under the
    legacy name to avoid an FE breaking change in this batch.
    """
    safe_job_id(job_id)
    safe_slug(project_id)
    settings = get_settings()
    log_path = job_log_path(current_ws(), project_id, job_id)
    runner = _get_runner()
    try:
        await runner.get(job_id)
        live_known = True
    except JobNotFoundError:
        live_known = False

    async def gen():
        seen = 0
        ended = False
        for _ in range(25):
            if log_path.exists():
                break
            await asyncio.sleep(0.2)
        if not log_path.exists():
            yield {"event": "error", "data": json.dumps({"error_code": "job_not_found"})}
            return
        while True:
            text = log_path.read_text(encoding="utf-8")
            lines = [ln for ln in text.split("\n") if ln.strip()]
            for ln in lines[seen:]:
                try:
                    blob = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                yield {"event": "job_event", "data": json.dumps(blob, ensure_ascii=False)}
                if blob.get("type") == "ended":
                    ended = True
            seen = len(lines)
            if ended:
                return
            if not live_known:
                return
            await asyncio.sleep(0.2)

    return EventSourceResponse(gen())
