import json
from pathlib import Path

from app.chat.log import append_event
from app.tools.projects import create_project


async def test_append_event_writes_one_line(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    log = workspace / pid / "chats" / f"{cid}.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"type": "user", "text": "hi"}


async def test_append_multiple_events(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    await append_event(workspace, pid, cid, {"type": "agent", "text": "hello"})
    lines = (workspace / pid / "chats" / f"{cid}.jsonl").read_text().splitlines()
    assert len(lines) == 2
