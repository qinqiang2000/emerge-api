"""B0 — `skill="audit"` jobs on JobRunner (2026-06-11 audit-board plan).

run_audit's judge trip on a large group (~70s) outlives Cowork's client tool
timeout (~60s); the job form lets clients start_job → poll get_job →
read_audit_report. The runner passes provider=None and lets run_audit's own
`_resolve_judge_provider` pick the judge — these tests monkeypatch that hook
(the same seam the tool path exercises)."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.jobs.runner import JobRunner, UnknownSkillError
from app.provider.base import ProviderResult
from app.schemas.job import JobStatus
from app.tools.match_prompt import write_audit_rules
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import audits_dir, docs_dir, docs_meta_dir


class _MockProvider:
    """Judge stub returning canned checks; optional delay to observe RUNNING."""

    def __init__(self, checks, delay: float = 0.0):
        self._checks = checks
        self._delay = delay
        self.calls = 0

    async def extract(self, *, model_id, system_prompt, user_content,
                      response_schema, params=None):
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        return ProviderResult(raw_json={"checks": self._checks}, model_id=model_id)


_DOCS = {"报价单.jpg": {}, "收货单.jpg": {}}

_CHECKS = [
    {"index": 0, "status": "pass", "reason": "甲方=环胜"},
    {"index": 1, "status": "fail", "reason": "未盖章"},
]


async def _audit_project(workspace: Path, *, rules: bool = True) -> str:
    """One audit project: docs in its own docs/ + rules (test_audit_run shape)."""
    slug = (await create_project(workspace, name="审核job"))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for fn in _DOCS:
        (docs_dir(workspace, slug) / fn).write_bytes(b"stub")
        atomic_write_json(
            docs_meta_dir(workspace, slug) / f"{fn}.json",
            {"filename": fn, "sha256": "x", "page_count": 1, "ext": "jpg"},
        )
    if rules:
        await write_audit_rules(workspace, slug, audit_rules=[
            "报价单甲方为环胜", "报价单盖红章",
        ])
    return slug


def _patch_judge(monkeypatch: pytest.MonkeyPatch, provider) -> None:
    """The runner passes provider=None; run_audit then resolves the judge via
    `_resolve_judge_provider` — patch that seam, proving the None-passthrough
    wiring actually reaches run_audit's own resolution."""
    from app.tools import audit_run as ar

    async def fake_resolve(ws, slug):
        return provider, "m"

    monkeypatch.setattr(ar, "_resolve_judge_provider", fake_resolve)


async def test_audit_job_done_event_and_report_on_disk(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = await _audit_project(workspace)
    p = _MockProvider(_CHECKS)
    _patch_judge(monkeypatch, p)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="audit", project_id=slug, params={})
    info = await runner.wait(job_id, timeout=5.0)

    assert info.status == JobStatus.DONE
    assert info.skill == "audit"
    assert p.calls == 1

    # final event carries the verdict headline, not the report body
    events_file = workspace / slug / "jobs" / f"{job_id}.jsonl"
    lines = [json.loads(ln) for ln in events_file.read_text().splitlines()]
    assert lines[0]["type"] == "started"
    ended = lines[-1]
    assert ended["type"] == "ended"
    assert ended["reason"] == "done"
    assert ended["overall"] == "fail"          # critical rule failed
    assert ended["checks_n"] == 2
    run_id = ended["run_id"]
    assert run_id

    # report body stays on disk — clients fetch via read_audit_report
    report_path = audits_dir(workspace, slug) / run_id / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["run_id"] == run_id
    assert report["overall"] == "fail"
    assert len(report["checks"]) == 2

    # JobInfo carries NO audit-specific fields; autoresearch fields stay None
    assert info.best_turn is None
    assert info.best_macro_f1 is None
    assert info.latest_turn == 0


async def test_audit_job_missing_rules_errors_with_audit_code(
    workspace: Path,
) -> None:
    slug = await _audit_project(workspace, rules=False)
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="audit", project_id=slug, params={})
    info = await runner.wait(job_id, timeout=5.0)

    assert info.status == JobStatus.ERROR
    assert info.error_code == "audit_no_rules"
    assert "write_audit_rules" in (info.error_message_en or "")

    events_file = workspace / slug / "jobs" / f"{job_id}.jsonl"
    ended = json.loads(events_file.read_text().splitlines()[-1])
    assert ended["type"] == "ended"
    assert ended["reason"] == "error"
    assert "audit" in ended["error"].lower() or "rules" in ended["error"]


async def test_audit_job_unexpected_failure_maps_generic_code(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = await _audit_project(workspace)

    # provider-level errors degrade to `unclear` inside the judge; raise from
    # audit_group itself to exercise the runner's generic exception mapping
    from app.tools import audit_run as ar

    async def boom(**kw):
        raise ValueError("judge blew up")

    monkeypatch.setattr(ar, "audit_group", boom)
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="audit", project_id=slug, params={})
    info = await runner.wait(job_id, timeout=5.0)

    assert info.status == JobStatus.ERROR
    assert info.error_code == "audit_failure"
    assert "ValueError" in (info.error_message_en or "")


async def test_audit_job_get_polls_running_then_done(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = await _audit_project(workspace)
    p = _MockProvider(_CHECKS, delay=0.3)   # judge trip in flight
    _patch_judge(monkeypatch, p)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(skill="audit", project_id=slug, params={})

    info = await runner.get(job_id)
    for _ in range(50):
        info = await runner.get(job_id)
        if info.status == JobStatus.RUNNING:
            break
        await asyncio.sleep(0.01)
    assert info.status == JobStatus.RUNNING

    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE
    assert (await runner.get(job_id)).status == JobStatus.DONE


async def test_audit_job_filenames_param_restricts_group(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    slug = await _audit_project(workspace)
    p = _MockProvider(_CHECKS)
    _patch_judge(monkeypatch, p)

    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    job_id = await runner.start(
        skill="audit", project_id=slug, params={"filenames": ["报价单.jpg"]},
    )
    info = await runner.wait(job_id, timeout=5.0)
    assert info.status == JobStatus.DONE

    events_file = workspace / slug / "jobs" / f"{job_id}.jsonl"
    ended = json.loads(events_file.read_text().splitlines()[-1])
    report_path = audits_dir(workspace, slug) / ended["run_id"] / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert set(report["group"]) == {"报价单.jpg"}


async def test_unknown_skill_still_raises(workspace: Path) -> None:
    slug = (await create_project(workspace, name="t"))["slug"]
    runner = JobRunner(workspace=workspace, provider=AsyncMock())
    with pytest.raises(UnknownSkillError):
        await runner.start(skill="not_a_skill", project_id=slug, params={})
