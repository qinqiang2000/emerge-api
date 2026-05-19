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
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    log = workspace / pid / "chats" / f"{cid}.jsonl"
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"type": "user", "text": "hi"}


async def test_append_multiple_events(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    await append_event(workspace, pid, cid, {"type": "agent", "text": "hello"})
    lines = (workspace / pid / "chats" / f"{cid}.jsonl").read_text().splitlines()
    assert len(lines) == 2


async def test_read_chat_events_roundtrip(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "hi"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "yo"})
    assert read_chat_events(workspace, pid, cid) == [
        {"type": "user", "text": "hi"},
        {"type": "agent_text", "text": "yo"},
    ]


def test_read_chat_events_missing_file(workspace: Path) -> None:
    assert read_chat_events(workspace, "p_nope", "c_nope") == []


async def test_read_chat_events_skips_partial_trailing_line(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cdir = chats_dir(workspace, pid)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "c_x.jsonl").write_text('{"type": "user", "text": "hi"}\n{"type": "agen')
    assert read_chat_events(workspace, pid, "c_x") == [{"type": "user", "text": "hi"}]


async def test_read_chat_events_unreadable_log_degrades_to_empty(workspace: Path) -> None:
    # A path that exists but can't be opened as a file (here: a directory) must
    # degrade to [] rather than bubbling an OSError out of GET /lab/chats/...
    pid = (await create_project(workspace, name="x"))["slug"]
    cdir = chats_dir(workspace, pid)
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "c_x.jsonl").mkdir(parents=True)
    assert read_chat_events(workspace, pid, "c_x") == []


async def test_session_id_sidecar_roundtrip(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    assert read_chat_session_id(workspace, pid, "c_x") is None
    write_chat_session_id(workspace, pid, "c_x", "sess-1")
    assert chat_meta_path(workspace, pid, "c_x").exists()
    assert read_chat_session_id(workspace, pid, "c_x") == "sess-1"
    # None clears it.
    write_chat_session_id(workspace, pid, "c_x", None)
    assert not chat_meta_path(workspace, pid, "c_x").exists()
    assert read_chat_session_id(workspace, pid, "c_x") is None
    # Clearing an already-absent sidecar is a no-op.
    write_chat_session_id(workspace, pid, "c_x", None)


async def test_read_chat_session_id_bad_json(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cdir = chats_dir(workspace, pid)
    cdir.mkdir(parents=True, exist_ok=True)
    chat_meta_path(workspace, pid, "c_x").write_text("{not json")
    assert read_chat_session_id(workspace, pid, "c_x") is None
    chat_meta_path(workspace, pid, "c_x").write_text('{"other_key": 1}')
    assert read_chat_session_id(workspace, pid, "c_x") is None


async def test_append_event_after_project_delete_is_no_op(workspace: Path) -> None:
    """Defensive: when the project dir is gone mid-turn (agent rm-rf'd or
    used delete_project), trailing SDK events (e.g. the `agent_text` that
    summarizes the deletion) must NOT resurrect `chats/` as a half-zombie
    folder. The chat log write should silently drop instead."""
    import shutil

    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_test"
    await append_event(workspace, pid, cid, {"type": "user", "text": "delete it"})
    # Simulate the agent deleting its own project mid-turn.
    shutil.rmtree(workspace / pid)
    # Trailing agent_text after the delete — must be dropped.
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "已删除"})
    # Sidecar writes (session id, ensure_chat_meta) must also be dropped.
    write_chat_session_id(workspace, pid, cid, "sess-x")
    assert not (workspace / pid).exists()
    assert not chat_meta_path(workspace, pid, cid).exists()


async def test_append_event_tombstone_drop_logs_warning(
    workspace: Path, caplog
) -> None:
    """Drops past the `_project_alive` gate are silent at the network layer
    (the SSE channel keeps streaming), but server logs must record them.
    Regression: a bare `Bash mv` project-root rename used to silently lose
    half the conversation; this warning is the breadcrumb."""
    import logging
    import shutil

    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_test"
    shutil.rmtree(workspace / pid)

    with caplog.at_level(logging.WARNING, logger="app.chat.log"):
        await append_event(
            workspace, pid, cid, {"type": "agent_text", "text": "lost"}
        )

    assert any(
        "tombstoned" in rec.message and pid in rec.message
        for rec in caplog.records
    )


async def test_rewind_to_last_user_truncates_and_clears_sidecar(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
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
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_only_agent"
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "hi"})
    before = read_chat_events(workspace, pid, cid)
    rewind_to_last_user(workspace, pid, cid)
    assert read_chat_events(workspace, pid, cid) == before


def test_rewind_to_last_user_missing_file_is_noop(workspace: Path) -> None:
    new_size = rewind_to_last_user(workspace, "p_nope", "c_nope")
    assert new_size == 0


async def test_rewind_to_last_user_idempotent(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_idem"
    await append_event(workspace, pid, cid, {"type": "user", "text": "first"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "ok"})
    rewind_to_last_user(workspace, pid, cid)
    after_first = read_chat_events(workspace, pid, cid)
    rewind_to_last_user(workspace, pid, cid)
    assert read_chat_events(workspace, pid, cid) == after_first


async def test_rewind_to_user_with_target_index(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
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
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_zero"
    await append_event(workspace, pid, cid, {"type": "user", "text": "u0"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a0"})
    rewind_to_user(workspace, pid, cid, target_user_index=0)
    assert read_chat_events(workspace, pid, cid) == []


async def test_rewind_to_user_target_index_out_of_range_is_noop(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    cid = "c_oor"
    await append_event(workspace, pid, cid, {"type": "user", "text": "u0"})
    await append_event(workspace, pid, cid, {"type": "agent_text", "text": "a0"})
    before = read_chat_events(workspace, pid, cid)
    rewind_to_user(workspace, pid, cid, target_user_index=5)
    assert read_chat_events(workspace, pid, cid) == before
    rewind_to_user(workspace, pid, cid, target_user_index=-1)
    assert read_chat_events(workspace, pid, cid) == before


# ── Unbound-chat branch (slug == "_chats") ────────────────────────────────


from app.chat.log import (
    _UNBOUND_SLUG,
    _unbound_chat_alive,
    ensure_chat_meta,
    list_unbound_chats,
    tombstone_unbound_chat,
    unbound_chat_tombstone_path,
)
from app.workspace.paths import (
    unbound_chat_log_path,
    unbound_chat_meta_path,
    unbound_chats_root,
)


_UCID = "c_unboundtest1"


async def test_unbound_append_writes_to_chats_root(workspace: Path) -> None:
    """`slug='_chats'` routes events to `_chats/<cid>.jsonl`, NOT to a
    `<slug>/chats/` tree. Bootstrap goes through `ensure_chat_meta` so the
    alive gate passes on turn 1."""
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="hi",
        has_attachments=False,
    )
    await append_event(
        workspace, _UNBOUND_SLUG, _UCID, {"type": "user", "text": "hi"},
    )
    log_path = unbound_chat_log_path(workspace, _UCID)
    assert log_path.exists()
    assert json.loads(log_path.read_text().splitlines()[0]) == {
        "type": "user", "text": "hi",
    }
    # No project folder was created.
    assert not (workspace / "_chats" / "project.json").exists()


async def test_unbound_read_chat_events_roundtrip(workspace: Path) -> None:
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="hi",
        has_attachments=False,
    )
    await append_event(workspace, _UNBOUND_SLUG, _UCID, {"type": "user", "text": "hi"})
    await append_event(workspace, _UNBOUND_SLUG, _UCID, {"type": "agent_text", "text": "yo"})
    assert read_chat_events(workspace, _UNBOUND_SLUG, _UCID) == [
        {"type": "user", "text": "hi"},
        {"type": "agent_text", "text": "yo"},
    ]


async def test_unbound_session_id_sidecar_roundtrip(workspace: Path) -> None:
    """SDK session-id resume needs the same meta sidecar for unbound chats —
    `read_chat_session_id` / `write_chat_session_id` must dispatch on
    `slug='_chats'` and read/write `_chats/<cid>.meta.json`."""
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="hi",
        has_attachments=False,
    )
    assert read_chat_session_id(workspace, _UNBOUND_SLUG, _UCID) is None
    write_chat_session_id(workspace, _UNBOUND_SLUG, _UCID, "sess-unbound")
    assert unbound_chat_meta_path(workspace, _UCID).exists()
    assert read_chat_session_id(workspace, _UNBOUND_SLUG, _UCID) == "sess-unbound"
    write_chat_session_id(workspace, _UNBOUND_SLUG, _UCID, None)
    # Sidecar still exists (label/kind/created_at remain), but session_id is gone.
    assert read_chat_session_id(workspace, _UNBOUND_SLUG, _UCID) is None
    assert unbound_chat_meta_path(workspace, _UCID).exists()


async def test_unbound_alive_gate_blocks_after_tombstone(workspace: Path) -> None:
    """After `tombstone_unbound_chat`, `_unbound_chat_alive` must return
    False, even if a racy `append_event` resurrects the jsonl mid-test."""
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="hi",
        has_attachments=False,
    )
    await append_event(workspace, _UNBOUND_SLUG, _UCID, {"type": "user", "text": "hi"})
    assert _unbound_chat_alive(workspace, _UCID)

    assert tombstone_unbound_chat(workspace, _UCID) is True
    assert not _unbound_chat_alive(workspace, _UCID)
    assert unbound_chat_tombstone_path(workspace, _UCID).exists()
    assert not unbound_chat_log_path(workspace, _UCID).exists()


async def test_unbound_append_after_tombstone_dropped_with_warning(
    workspace: Path, caplog
) -> None:
    """Trailing SDK events after DELETE — must be dropped and surfaced in
    server logs. The warning is the breadcrumb for "where did half my
    conversation go" debugging."""
    import logging

    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, _UCID,
        first_user_message="hi",
        has_attachments=False,
    )
    await append_event(workspace, _UNBOUND_SLUG, _UCID, {"type": "user", "text": "hi"})
    tombstone_unbound_chat(workspace, _UCID)

    with caplog.at_level(logging.WARNING, logger="app.chat.log"):
        await append_event(
            workspace, _UNBOUND_SLUG, _UCID,
            {"type": "agent_text", "text": "trailing"},
        )
    assert any(
        "unbound chat tombstoned" in rec.message and _UCID in rec.message
        for rec in caplog.records
    )


async def test_list_unbound_chats_orders_newest_first(workspace: Path) -> None:
    """The listing endpoint must surface every alive chat, sorted by
    `created_at` descending. Tombstoned chats are filtered."""
    for cid, label in [("c_unb000000a01", "first"), ("c_unb000000b02", "second")]:
        ensure_chat_meta(
            workspace, _UNBOUND_SLUG, cid,
            first_user_message=label, has_attachments=False,
        )
        await append_event(
            workspace, _UNBOUND_SLUG, cid, {"type": "user", "text": label},
        )

    out = list_unbound_chats(workspace)
    assert len(out) == 2
    # Both ts_iso come from `created_at`; order isn't guaranteed within the
    # same second so we just confirm the set + shape.
    labels = sorted(c["label"] for c in out)
    assert labels == ["first", "second"]
    for chat in out:
        assert chat["kind"] == "chat"
        assert chat["n_events"] == 1
        assert chat["attachment_count"] == 0
        assert chat["chat_id"].startswith("c_")


async def test_list_unbound_chats_skips_tombstoned(workspace: Path) -> None:
    ensure_chat_meta(
        workspace, _UNBOUND_SLUG, "c_unb000zombie",
        first_user_message="rip", has_attachments=False,
    )
    await append_event(
        workspace, _UNBOUND_SLUG, "c_unb000zombie", {"type": "user", "text": "rip"},
    )
    tombstone_unbound_chat(workspace, "c_unb000zombie")
    out = list_unbound_chats(workspace)
    assert out == []


def test_list_unbound_chats_returns_empty_when_root_missing(workspace: Path) -> None:
    assert not unbound_chats_root(workspace).exists()
    assert list_unbound_chats(workspace) == []


def test_tombstone_unbound_chat_idempotent_on_missing(workspace: Path) -> None:
    """Tombstoning a chat that never existed must not crash. Returns False
    (nothing was on disk) and still drops the marker so a future racy write
    is still gated."""
    assert tombstone_unbound_chat(workspace, "c_neverexisted") is False
    assert unbound_chat_tombstone_path(workspace, "c_neverexisted").exists()
