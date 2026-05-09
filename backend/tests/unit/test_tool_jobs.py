from pathlib import Path
from unittest.mock import AsyncMock

from app.jobs.runner import JobRunner
from app.schemas.job import JobInfo, JobStatus
from app.tools import jobs as tool_jobs


async def test_start_job_returns_job_id(workspace: Path) -> None:
    runner = AsyncMock(spec=JobRunner)
    runner.start.return_value = "j_abc123def456"
    out = await tool_jobs.start_job_impl(runner, skill="autoresearch", project_id="p_x", params={"max_turn": 10})
    assert out == "j_abc123def456"
    runner.start.assert_awaited_once_with(skill="autoresearch", project_id="p_x", params={"max_turn": 10})


async def test_get_job_returns_info_dict(workspace: Path) -> None:
    runner = AsyncMock(spec=JobRunner)
    runner.get.return_value = JobInfo(
        job_id="j_x", project_id="p_x", skill="autoresearch",
        status=JobStatus.RUNNING, params={}, created_at="t",
    )
    out = await tool_jobs.get_job_impl(runner, job_id="j_x")
    assert out["status"] == "running"
    assert out["job_id"] == "j_x"
