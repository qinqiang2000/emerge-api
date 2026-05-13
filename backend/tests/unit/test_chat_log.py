import json
from pathlib import Path

from app.chat.log import (
    append_event,
    read_chat_events,
    read_chat_session_id,
    rewind_to_last_user,
    rewind_to_user,
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


def test_read_chat_events_unreadable_log_degrades_to_empty(workspace: Path) -> None:
    # A path that exists but can't be opened as a file (here: a directory) must
    # degrade to [] rather than bubbling an OSError out of GET /lab/chats/...
    cdir = chats_dir(workspace, "p_x")
    (cdir / "c_x.jsonl").mkdir(parents=True)
    assert read_chat_events(workspace, "p_x", "c_x") == []


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


async def test_rewind_to_last_user_truncates_and_clears_sidecar(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_rewind"
    await append_event(workspace, pid, cid, {"type": "user", "text": "first"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "ok"})
    await append_event(workspace, pid, cid, {"type": "user", "text": "second"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "ok2"})
    write_chat_session_id(workspace, pid, cid, "sess-x")

    new_size = rewind_to_last_user(workspace, pid, cid)

    events = read_chat_events(workspace, pid, cid)
    assert events == [
        {"type": "user", "text": "first"},
        {"type": "agent_text", "text": "ok"},
    ]
    log_path = chats_dir(workspace, pid) / f"{cid}.jsonl"
    assert log_path.stat().st_size == new_size
    assert read_chat_session_id(workspace, pid, cid) is None


async def test_rewind_to_last_user_no_user_line_is_noop(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_only_agent"
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "hi"})
    before = read_chat_events(workspace, pid, cid)
    rewind_to_last_user(workspace, pid, cid)
    assert read_chat_events(workspace, pid, cid) == before


def test_rewind_to_last_user_missing_file_is_noop(workspace: Path) -> None:
    new_size = rewind_to_last_user(workspace, "p_nope", "c_nope")
    assert new_size == 0


async def test_rewind_to_last_user_idempotent(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_idem"
    await append_event(workspace, pid, cid, {"type": "user", "text": "first"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "ok"})
    rewind_to_last_user(workspace, pid, cid)
    after_first = read_chat_events(workspace, pid, cid)
    rewind_to_last_user(workspace, pid, cid)
    assert read_chat_events(workspace, pid, cid) == after_first


async def test_rewind_to_user_with_target_index(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_target"
    await append_event(workspace, pid, cid, {"type": "user", "text": "u0"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a0"})
    await append_event(workspace, pid, cid, {"type": "user", "text": "u1"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a1"})
    await append_event(workspace, pid, cid, {"type": "user", "text": "u2"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a2"})

    # Truncate at the 2nd user (index 1) → keep u0 + a0.
    rewind_to_user(workspace, pid, cid, target_user_index=1)
    assert read_chat_events(workspace, pid, cid) == [
        {"type": "user", "text": "u0"},
        {"type": "agent_text", "text": "a0"},
    ]


async def test_rewind_to_user_target_index_zero(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_zero"
    await append_event(workspace, pid, cid, {"type": "user", "text": "u0"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a0"})
    rewind_to_user(workspace, pid, cid, target_user_index=0)
    assert read_chat_events(workspace, pid, cid) == []


async def test_rewind_to_user_target_index_out_of_range_is_noop(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_oor"
    await append_event(workspace, pid, cid, {"type": "user", "text": "u0"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a0"})
    before = read_chat_events(workspace, pid, cid)
    rewind_to_user(workspace, pid, cid, target_user_index=5)
    assert read_chat_events(workspace, pid, cid) == before
    rewind_to_user(workspace, pid, cid, target_user_index=-1)
    assert read_chat_events(workspace, pid, cid) == before
