import json
from pathlib import Path

from app.chat.log import (
    append_event,
    read_chat_events,
    read_chat_session_id,
    write_chat_session_id,
)
from app.tools.projects import create_project
from app.workspace.paths import chat_meta_path, chats_dir


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


async def test_read_chat_events_roundtrip(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "yo"})
    assert read_chat_events(workspace, pid, cid) == [
        {"type": "user", "text": "hi"},
        {"type": "agent_text", "text": "yo"},
    ]


def test_read_chat_events_missing_file(workspace: Path) -> None:
    assert read_chat_events(workspace, "p_nope", "c_nope") == []


def test_read_chat_events_skips_partial_trailing_line(workspace: Path) -> None:
    cdir = chats_dir(workspace, "p_x")
    cdir.mkdir(parents=True)
    (cdir / "c_x.jsonl").write_text('{"type": "user", "text": "hi"}\n{"type": "agen')
    assert read_chat_events(workspace, "p_x", "c_x") == [{"type": "user", "text": "hi"}]


def test_session_id_sidecar_roundtrip(workspace: Path) -> None:
    assert read_chat_session_id(workspace, "p_x", "c_x") is None
    write_chat_session_id(workspace, "p_x", "c_x", "sess-1")
    assert chat_meta_path(workspace, "p_x", "c_x").exists()
    assert read_chat_session_id(workspace, "p_x", "c_x") == "sess-1"
    # None clears it.
    write_chat_session_id(workspace, "p_x", "c_x", None)
    assert not chat_meta_path(workspace, "p_x", "c_x").exists()
    assert read_chat_session_id(workspace, "p_x", "c_x") is None
    # Clearing an already-absent sidecar is a no-op.
    write_chat_session_id(workspace, "p_x", "c_x", None)


def test_read_chat_session_id_bad_json(workspace: Path) -> None:
    cdir = chats_dir(workspace, "p_x")
    cdir.mkdir(parents=True)
    chat_meta_path(workspace, "p_x", "c_x").write_text("{not json")
    assert read_chat_session_id(workspace, "p_x", "c_x") is None
    chat_meta_path(workspace, "p_x", "c_x").write_text('{"other_key": 1}')
    assert read_chat_session_id(workspace, "p_x", "c_x") is None
