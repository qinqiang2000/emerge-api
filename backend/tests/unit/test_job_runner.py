import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs import autoresearch as ar
from app.jobs.runner import JobNotFoundError, JobRunner, UnknownSkillError
from app.schemas.job import JobStatus
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.tools.projects import create_project
from app.tools.schema import write_schema


def _fake_score(field_accuracy_macro: float) -> ScoreResult:
    # M12.x — runner observes the accuracy headline; F1 family is None.
    return ScoreResult(
        n_docs=1, n_reviewed=1,
        field_accuracy_macro=field_accuracy_macro,
        macro_f1=None,
        per_field=[FieldScore(
            field="x", accuracy=field_accuracy_macro,
            correct=1, total=1, n_absent_both=0, not_applicable=False,
        )],
        errors=[], ts="t", schema_field_count=1,
    )


@pytest.fixture
def patched_loop(monkeypatch: pytest.MonkeyPatch):
    """Replace propose_schema and score_with_schema with deterministic stubs.
    Score sequence improves once then plateaus, so the loop ends quickly."""
    seq = [0.5, 0.7]

    async def _score(**kwargs):
        i = min(len(seq) - 1, _score.calls)
        _score.calls += 1
        return _fake_score(seq[i]), {}
    _score.calls = 0

    async def _propose(**kwargs):
        return kwargs["schema"], "rat", [], []

    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)


async def test_runner_starts_and_completes(workspace: Path, patched_loop) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 1})
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE
    events_file = workspace / pid / "jobs" / f"{job_id}.jsonl"
    assert events_file.exists()
    types = [json.loads(ln)["type"] for ln in events_file.read_text().splitlines()]
    assert types[0] == "started"
    assert types[-1] == "ended"


async def test_runner_cancel(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )

    async def _score(**kwargs):
        await asyncio.sleep(0.2)
        return _fake_score(0.5), {}
    async def _propose(**kwargs):
        return kwargs["schema"], "rat", [], []
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 30})
    await asyncio.sleep(0.05)
    await runner.cancel(job_id)
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.CANCELLED


async def test_runner_pause_resume(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    seq = [0.5, 0.6, 0.7, 0.8]

    async def _score(**kwargs):
        i = min(len(seq) - 1, _score.calls)
        _score.calls += 1
        await asyncio.sleep(0.02)
        return _fake_score(seq[i]), {}
    _score.calls = 0
    async def _propose(**kwargs):
        return kwargs["schema"], "rat", [], []
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 3})
    await asyncio.sleep(0.05)
    await runner.pause(job_id)
    info = await runner.get(job_id)
    for _ in range(20):
        info = await runner.get(job_id)
        if info.status == JobStatus.PAUSED:
            break
        await asyncio.sleep(0.02)
    assert info.status == JobStatus.PAUSED
    await runner.resume(job_id)
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE


async def test_runner_get_unknown_raises(workspace: Path) -> None:
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    with pytest.raises(JobNotFoundError):
        await runner.get("j_nonexistentaa")


async def test_runner_unknown_skill_raises(workspace: Path) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    with pytest.raises(UnknownSkillError):
        await runner.start(skill="not_a_skill", project_id=pid, params={})


async def test_runner_error_includes_type(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )

    async def _score(**kwargs):
        raise ValueError("")  # empty message — the case that was hard to diagnose
    async def _propose(**kwargs):
        return kwargs["schema"], "rat", [], []
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="autoresearch", project_id=pid, params={"max_turn": 1})
    info = await runner.wait(job_id, timeout=5.0)

    assert info.status == JobStatus.ERROR
    assert info.error_message_en == "ValueError: "

    events_file = workspace / pid / "jobs" / f"{job_id}.jsonl"
    ended = json.loads(events_file.read_text().splitlines()[-1])
    assert ended["type"] == "ended"
    assert ended["error"] == "ValueError: "


def test_safe_job_id_validates() -> None:
    from app.api.routes._safety import safe_job_id
    from fastapi import HTTPException
    assert safe_job_id("j_abc123def456") == "j_abc123def456"
    with pytest.raises(HTTPException):
        safe_job_id("../etc/passwd")


async def test_get_runner_singleton(workspace: Path) -> None:
    from app.jobs import get_runner, reset_runner_for_tests
    reset_runner_for_tests()
    a = get_runner(workspace=workspace, provider=AsyncMock())
    b = get_runner(workspace=workspace, provider=AsyncMock())
    assert a is b
    reset_runner_for_tests()
