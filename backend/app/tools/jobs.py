from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.jobs.runner import JobRunner


async def start_job_impl(runner: "JobRunner", *, skill: str, project_id: str, params: dict[str, Any]) -> str:
    return await runner.start(skill=skill, project_id=project_id, params=params)


async def get_job_impl(runner: "JobRunner", *, job_id: str) -> dict[str, Any]:
    info = await runner.get(job_id)
    return info.model_dump(mode="json")


async def pause_job_impl(runner: "JobRunner", *, job_id: str) -> None:
    await runner.pause(job_id)


async def resume_job_impl(runner: "JobRunner", *, job_id: str) -> None:
    await runner.resume(job_id)


async def cancel_job_impl(runner: "JobRunner", *, job_id: str) -> None:
    await runner.cancel(job_id)
