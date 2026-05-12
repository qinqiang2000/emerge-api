from pathlib import Path

from app.chat.log import (
    append_event,
    derive_chat_kind,
    derive_chat_label,
    ensure_chat_meta,
    list_chats,
    read_chat_meta,
    read_chat_session_id,
    write_chat_session_id,
)
from app.tools.projects import create_project
from app.workspace.paths import chat_meta_path


def test_derive_chat_kind_slash_command_map() -> None:
    # Mapping is slash-cmd → generic verb (intentionally many-to-one).
    assert derive_chat_kind("/init us-invoice", has_attachments=False) == "init"
    assert derive_chat_kind("/extract", has_attachments=False) == "run"
    assert derive_chat_kind("/eval", has_attachments=False) == "run"
    assert derive_chat_kind("/improve", has_attachments=False) == "tune"
    assert derive_chat_kind("/publish v2", has_attachments=False) == "publish"
    assert derive_chat_kind("/review", has_attachments=False) == "review"
    # Leading whitespace tolerated (chat service prepends a space to slash cmds).
    assert derive_chat_kind("  /improve", has_attachments=False) == "tune"
    # Free-text → chat.
    assert derive_chat_kind("why did due_date change?", has_attachments=False) == "chat"
    # Attachments on the first message → ingest, regardless of the text.
    assert derive_chat_kind("here are the files", has_attachments=True) == "ingest"
    assert derive_chat_kind("/extract", has_attachments=True) == "ingest"


def test_derive_chat_label_strips_leading_command_and_truncates() -> None:
    assert derive_chat_label("/improve") == "improve"
    assert derive_chat_label("/init us-invoice extraction") == "us-invoice extraction"
    assert derive_chat_label("  /publish v2 to live  ") == "v2 to live"
    long = "extract every line item including unit price quantity and tax for all docs"
    out = derive_chat_label(long)
    assert len(out) <= 40
    assert out == long[:40].rstrip()
    assert derive_chat_label("   ") == "untitled"


async def test_ensure_chat_meta_sets_once_and_is_idempotent(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_aaaaaaaaaaaa"
    ensure_chat_meta(workspace, pid, cid, first_user_message="/improve", has_attachments=False)
    meta1 = read_chat_meta(workspace, pid, cid)
    assert meta1["kind"] == "tune"
    assert meta1["label"] == "improve"
    assert isinstance(meta1["created_at"], str) and meta1["created_at"]
    # Calling again with a different message must NOT overwrite kind/label/created_at.
    ensure_chat_meta(workspace, pid, cid, first_user_message="/publish", has_attachments=False)
    meta2 = read_chat_meta(workspace, pid, cid)
    assert meta2 == meta1


async def test_session_id_write_preserves_kind_label(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    cid = "c_bbbbbbbbbbbb"
    ensure_chat_meta(workspace, pid, cid, first_user_message="/extract", has_attachments=False)
    write_chat_session_id(workspace, pid, cid, "sess-9")
    meta = read_chat_meta(workspace, pid, cid)
    assert meta["sdk_session_id"] == "sess-9"
    assert meta["kind"] == "run"
    assert meta["label"] == "extract"
    assert read_chat_session_id(workspace, pid, cid) == "sess-9"
    # Clearing the session id leaves kind/label intact (file is NOT deleted).
    write_chat_session_id(workspace, pid, cid, None)
    meta = read_chat_meta(workspace, pid, cid)
    assert "sdk_session_id" not in meta
    assert meta["kind"] == "run"
    assert chat_meta_path(workspace, pid, cid).exists()


async def test_session_id_only_sidecar_is_deleted_on_clear(workspace: Path) -> None:
    # No ensure_chat_meta call → sidecar holds only sdk_session_id → clearing removes it.
    pid = await create_project(workspace, name="x")
    cid = "c_cccccccccccc"
    write_chat_session_id(workspace, pid, cid, "sess-1")
    assert chat_meta_path(workspace, pid, cid).exists()
    write_chat_session_id(workspace, pid, cid, None)
    assert not chat_meta_path(workspace, pid, cid).exists()


async def test_list_chats_sorted_desc_by_created_at(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    # Three chats, meta created_at out of file-order so sort is exercised.
    for cid, msg, ts in [
        ("c_111111111111", "/init x", "2026-05-10T08:00:00+00:00"),
        ("c_222222222222", "/extract", "2026-05-12T09:00:00+00:00"),
        ("c_333333333333", "why?", "2026-05-11T12:00:00+00:00"),
    ]:
        await append_event(workspace, pid, cid, {"type": "user", "text": msg})
        await append_event(workspace, pid, cid, {"type": "agent_text", "text": "ok"})
        ensure_chat_meta(workspace, pid, cid, first_user_message=msg, has_attachments=False)
        # Pin created_at deterministically for the assertion.
        import json
        p = chat_meta_path(workspace, pid, cid)
        d = json.loads(p.read_text())
        d["created_at"] = ts
        p.write_text(json.dumps(d))
    out = list_chats(workspace, pid)
    assert [c["chat_id"] for c in out] == ["c_222222222222", "c_333333333333", "c_111111111111"]
    assert out[0] == {
        "chat_id": "c_222222222222",
        "label": "extract",
        "kind": "run",
        "ts_iso": "2026-05-12T09:00:00+00:00",
        "n_events": 2,
    }


def test_list_chats_empty_when_no_chats(workspace: Path) -> None:
    # Project dir may not even have a chats/ subdir yet.
    assert list_chats(workspace, "p_doesnotexist") == []


async def test_list_chats_falls_back_to_first_line_for_legacy_logs(workspace: Path) -> None:
    # Pre-M8 logs have a .jsonl but no .meta.json — derive kind/label from line 1,
    # ts from file mtime (just assert it's a non-empty iso-ish string).
    pid = await create_project(workspace, name="x")
    cid = "c_legacy000000"
    await append_event(workspace, pid, cid, {"type": "user", "text": "/improve"})
    out = list_chats(workspace, pid)
    assert len(out) == 1
    assert out[0]["chat_id"] == cid
    assert out[0]["kind"] == "tune"
    assert out[0]["label"] == "improve"
    assert isinstance(out[0]["ts_iso"], str) and out[0]["ts_iso"]
    assert out[0]["n_events"] == 1
