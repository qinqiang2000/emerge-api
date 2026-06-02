from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

from app.jobs import autoresearch as ar
from app.jobs.events import append_event_jsonl, now_iso_filename_safe
from app.provider.base import Provider
from app.schemas.job import JobEvent, JobInfo, JobStatus
from app.workspace.ids import new_job_id
from app.workspace.paths import job_log_path


class JobNotFoundError(KeyError):
    pass


class UnknownSkillError(ValueError):
    pass


@dataclass
class _JobHandle:
    info: JobInfo
    task: asyncio.Task[Any]
    pause_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class JobRunner:
    """Process-wide registry of running jobs.

    For now there is no concurrency cap (single-user lab tool); the loop's
    extract calls naturally pace it. Crash recovery is M3 territory.

    Note: no `model_id` field. The proposer model for each autoresearch job
    is resolved at `start()` via `_resolve_proposer_model`, which inspects
    the project's active ModelConfig (with override / env fallback). The
    previous design pinned a single env-seeded model on the singleton,
    silently bypassing `switch_active_model` for autoresearch — see
    `default-extract-model-prompts-ev-eager-turing` plan."""

    def __init__(self, *, workspace: Path, provider: Provider) -> None:
        self.workspace = workspace
        # `provider` is retained for back-compat with callers that pass a
        # process-wide default; it's no longer used during job execution
        # (each job resolves its own provider via `_resolve_proposer_model`),
        # but tests like `test_get_runner_singleton` still construct it.
        self.provider = provider
        self._jobs: dict[str, _JobHandle] = {}
        self._lock = asyncio.Lock()

    async def start(
        self, *, skill: str, project_id: str, params: dict[str, Any],
    ) -> str:
        if skill != "autoresearch":
            raise UnknownSkillError(f"unknown skill: {skill!r}")
        from app.tools.schema import read_schema
        initial_schema = await read_schema(self.workspace, project_id)
        if not initial_schema:
            raise ValueError("project has empty schema; nothing to autoresearch")
        # Resolve the proposer model NOW (at job start) so the live
        # `project.json.active_model_id` wins over any process-wide default.
        # `proposer_model` may be passed via `params` for per-job overrides
        # — see `_resolve_proposer_model` for the full chain.
        override = params.get("proposer_model")
        if override is not None and not isinstance(override, str):
            override = None
        proposer_provider, proposer_model_id = await ar._resolve_proposer_model(
            self.workspace, project_id, override=override,
        )
        job_id = new_job_id()
        info = JobInfo(
            job_id=job_id, project_id=project_id, skill=skill,
            status=JobStatus.PENDING, params=params,
            created_at=now_iso_filename_safe(),
        )
        pause_event = asyncio.Event()
        cancel_event = asyncio.Event()
        log_path = job_log_path(self.workspace, project_id, job_id)

        async def emit(ev: JobEvent) -> None:
            await append_event_jsonl(log_path, ev)
            data = ev.model_dump(mode="json")
            if ev.type == "turn":
                handle.info.latest_turn = int(data.get("turn", handle.info.latest_turn))
                if data.get("saved"):
                    handle.info.best_turn = handle.info.latest_turn
                    handle.info.best_macro_f1 = float(data["macro_f1"])
            elif ev.type == "paused":
                handle.info.status = JobStatus.PAUSED
            elif ev.type == "resumed":
                handle.info.status = JobStatus.RUNNING

        async def _run() -> JobInfo:
            handle.info.status = JobStatus.RUNNING
            try:
                raw_targets = params.get("target_fields")
                target_fields = (
                    [str(f) for f in raw_targets if isinstance(f, str)]
                    if isinstance(raw_targets, list) and raw_targets
                    else None
                )
                ar_params = ar.AutoresearchParams(
                    max_turn=int(params.get("max_turn", 30)),
                    early_stop_no_improvement=int(params.get("early_stop_no_improvement", 5)),
                    target_fields=target_fields,
                )
                final = await ar.run_autoresearch_loop(
                    workspace=self.workspace, project_id=project_id, job_id=job_id,
                    initial_schema=initial_schema,
                    provider=proposer_provider, model_id=proposer_model_id,
                    params=ar_params, emit=emit,
                    cancel_event=cancel_event, pause_event=pause_event,
                )
                handle.info.status = final.status
                handle.info.best_turn = final.best_turn
                handle.info.best_macro_f1 = final.best_macro_f1
                return handle.info
            except Exception as exc:
                log.exception("autoresearch job %s failed", job_id)
                _err = f"{type(exc).__name__}: {exc}"
                handle.info.status = JobStatus.ERROR
                handle.info.error_code = "autoresearch_failure"
                handle.info.error_message_en = _err
                await append_event_jsonl(
                    log_path,
                    JobEvent(type="ended", ts=now_iso_filename_safe(),
                             reason="error", error=_err),
                )
                return handle.info

        task = asyncio.create_task(_run(), name=f"job:{job_id}")
        handle = _JobHandle(info=info, task=task,
                            pause_event=pause_event, cancel_event=cancel_event)
        async with self._lock:
            self._jobs[job_id] = handle
        return job_id

    async def get(self, job_id: str) -> JobInfo:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        return handle.info

    async def wait(self, job_id: str, *, timeout: float | None = None) -> JobInfo:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        await asyncio.wait_for(handle.task, timeout=timeout)
        return handle.info

    async def pause(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.pause_event.set()

    async def resume(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.pause_event.clear()
        handle.info.status = JobStatus.RUNNING

    async def cancel(self, job_id: str) -> None:
        handle = self._jobs.get(job_id)
        if handle is None:
            raise JobNotFoundError(job_id)
        handle.cancel_event.set()
        handle.pause_event.clear()
