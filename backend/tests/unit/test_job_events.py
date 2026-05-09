from datetime import datetime, timezone
from pathlib import Path

from app.jobs.events import append_event_jsonl, now_iso_filename_safe, read_events
from app.schemas.job import JobEvent


async def test_append_then_read(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    await append_event_jsonl(p, JobEvent(type="started", ts="t0"))
    await append_event_jsonl(p, JobEvent(type="turn", ts="t1", turn=1, macro_f1=0.5))
    events = await read_events(p)
    assert [e.type for e in events] == ["started", "turn"]
    assert events[1].model_dump(mode="json")["macro_f1"] == 0.5


async def test_read_partial_trailing_line(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "j_xyz.jsonl"
    await append_event_jsonl(p, JobEvent(type="started", ts="t0"))
    # Simulate crash mid-write
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write('{"type": "turn", "ts":')   # truncated, no newline
    events = await read_events(p)
    assert len(events) == 1
    assert events[0].type == "started"


async def test_read_missing_file_returns_empty(workspace: Path) -> None:
    p = workspace / "p_abc" / "jobs" / "missing.jsonl"
    events = await read_events(p)
    assert events == []


def test_now_iso_filename_safe_format() -> None:
    s = now_iso_filename_safe()
    # 2026-05-09T01-23-45Z — no colons (filename-safe)
    assert "Z" in s and ":" not in s
