import pytest
from pydantic import ValidationError

from app.schemas.job import JobEvent, JobInfo, JobStatus


def test_job_status_values() -> None:
    assert {s.value for s in JobStatus} == {
        "pending", "running", "paused", "done", "cancelled", "error",
    }


def test_job_info_minimal() -> None:
    info = JobInfo(
        job_id="j_abc123def456",
        project_id="p_abc123def456",
        skill="autoresearch",
        status=JobStatus.RUNNING,
        params={"max_turn": 30},
        created_at="2026-05-09T00-00-00Z",
    )
    assert info.skill == "autoresearch"
    assert info.status == JobStatus.RUNNING
    assert info.best_turn is None
    assert info.best_macro_f1 is None
    assert info.latest_turn == 0


def test_job_info_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        JobInfo(
            job_id="j_x", project_id="p_x", skill="autoresearch",
            status=JobStatus.RUNNING, params={}, created_at="x", unknown=1,
        )


def test_job_event_round_trip() -> None:
    ev = JobEvent(type="turn", turn=3, macro_f1=0.78, ts="2026-05-09T00-00-00Z")
    blob = ev.model_dump(mode="json")
    assert blob["type"] == "turn"
    assert blob["turn"] == 3
    assert blob["macro_f1"] == 0.78


def test_job_event_extra_allowed() -> None:
    """JobEvent allows arbitrary keys per event type — schema is loose by design.
    Strict typing happens at consumer parse time."""
    ev = JobEvent(type="started", ts="x", arbitrary_key="value")
    assert ev.model_dump(mode="json").get("arbitrary_key") == "value"
