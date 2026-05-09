import asyncio
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.jobs import autoresearch as ar
from app.jobs import reset_runner_for_tests
from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.tools.projects import create_project
from app.tools.schema import write_schema


def _fake_score(macro_f1):
    return ScoreResult(
        n_docs=1, n_reviewed=1, macro_f1=macro_f1,
        per_field=[FieldScore(field="x", tp=1, fp=0, fn=0, support=1,
                              precision=1.0, recall=1.0, f1=macro_f1)],
        errors=[], ts="t", schema_field_count=1,
    )


@pytest.fixture(autouse=True)
def _reset_runner_singleton():
    reset_runner_for_tests()
    yield
    reset_runner_for_tests()


async def test_get_job_status(workspace: Path, monkeypatch) -> None:
    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )

    async def _score(**kwargs): return _fake_score(0.5), {}
    async def _propose(**kwargs): return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    client = TestClient(app)
    r = client.post(f"/lab/jobs", json={"skill": "autoresearch", "project_id": pid, "params": {"max_turn": 0}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    await asyncio.sleep(0.2)
    r2 = client.get(f"/lab/jobs/{job_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["job_id"] == job_id
    assert body["status"] in ("running", "done")


def test_get_job_events_sse_streams(workspace: Path, monkeypatch) -> None:
    """Smoke: connecting to the SSE endpoint returns an event-stream content
    type and at least one line. Full event semantics are covered in
    test_autoresearch_loop / test_job_runner."""
    pid = "p_aaaaaaaaaaaa"
    job_id = "j_xxxxxxxxxxxx"
    p = workspace / pid / "jobs" / f"{job_id}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"type": "started", "ts": "t0"}) + "\n", encoding="utf-8")

    client = TestClient(app)
    with client.stream("GET", f"/lab/jobs/{job_id}/events?project_id={pid}") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        body = b""
        for chunk in r.iter_raw():
            body += chunk
            if b"\"type\": \"started\"" in body:
                break
        assert b"started" in body


def test_get_job_unknown_id_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/jobs/j_nonexistenta")
    assert r.status_code == 404


async def test_post_job_cancel(workspace: Path, monkeypatch) -> None:
    async def _score(**kwargs):
        await asyncio.sleep(0.5)
        return _fake_score(0.5), {}
    async def _propose(**kwargs): return kwargs["schema"], "rat"
    monkeypatch.setattr(ar, "score_with_schema", _score)
    monkeypatch.setattr(ar, "propose_schema", _propose)

    pid = await create_project(workspace, name="t")
    await write_schema(
        workspace, pid,
        [SchemaField(name="x", type=FieldType.STRING, description="d")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.post("/lab/jobs", json={"skill": "autoresearch", "project_id": pid, "params": {"max_turn": 30}})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    rc = client.post(f"/lab/jobs/{job_id}/cancel")
    assert rc.status_code == 200
