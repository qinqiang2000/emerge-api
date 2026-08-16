from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequest, CallToolRequestParams

from app.jobs.runner import JobRunner
from app.schemas.job import JobInfo, JobStatus
from app.tools import build_emerge_mcp, registered_tool_names
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


# P4 Task 8 — control_job(action=) folds pause/resume/cancel_job. The three
# had byte-identical `(job_id)` schemas and were all idempotent — same noun,
# same shape, same policy.
@pytest.mark.parametrize(
    "action,expected_text",
    [("pause", "paused"), ("resume", "resumed"), ("cancel", "cancelled")],
)
async def test_control_job_dispatches_each_action(
    workspace: Path, stub_provider: AsyncMock, monkeypatch,
    action: str, expected_text: str,
) -> None:
    """The three job-control tools had byte-identical `(job_id)` schemas and
    were all idempotent — same noun, same shape, same policy."""
    # JobRunner.pause/resume/cancel are async and return None; the tool goes
    # through jobs_mod.{action}_job_impl(job_runner, job_id=...). Patch that
    # layer so the test pins the dispatch, not the runner internals.
    impl = AsyncMock(return_value=None)
    monkeypatch.setattr(f"app.tools.jobs.{action}_job_impl", impl)
    server = build_emerge_mcp(
        workspace=workspace, provider=stub_provider, job_runner=MagicMock(),
    )
    handler = server["instance"].request_handlers[CallToolRequest]
    res = await handler(CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(
            name="control_job", arguments={"job_id": "j_1", "action": action},
        ),
    ))
    impl.assert_awaited_once()
    assert impl.await_args.kwargs["job_id"] == "j_1"
    # Return text must stay byte-identical to the tool it replaced.
    assert res.root.content[0].text == expected_text


def test_old_job_control_names_are_gone() -> None:
    live = registered_tool_names(headless=True)
    for old in ("pause_job", "resume_job", "cancel_job"):
        assert old not in live
    assert "control_job" in live
    assert {"start_job", "get_job"} <= live, "start/get must NOT be folded in"
