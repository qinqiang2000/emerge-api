"""HTTP-level coverage of the new `/lab/chats` family (unbound chats).

  - `POST /lab/chats` mints a fresh chat_id (no storage).
  - `GET /lab/chats` lists unbound chats, newest first.
  - `GET /lab/chats/{cid}/events` replays the unbound log.
  - `POST /lab/chats/{cid}/promote` returns `{slug, project_id}` and moves
    the chat under the project.
  - `DELETE /lab/chats/{cid}` tombstones (so subsequent appends drop).
  - Route order: a chat-id-shaped path doesn't get matched against the
    project-slug `GET /lab/chats/{slug}` route.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.chat.log import (
    append_event,
    ensure_chat_meta,
    unbound_chat_tombstone_path,
)
from app.chat.service import _UNBOUND_SLUG
from app.config import get_settings
from app.main import app
from app.workspace.paths import (
    chats_dir,
    unbound_chat_attachments_dir,
    unbound_chat_log_path,
    unbound_chats_root,
)


client = TestClient(app)


def test_post_lab_chats_mints_chat_id(workspace: Path) -> None:
    r = client.post("/lab/chats")
    assert r.status_code == 200
    body = r.json()
    assert "chat_id" in body
    cid = body["chat_id"]
    assert cid.startswith("c_")
    # No storage on disk yet — first event materialises `_chats/<cid>.jsonl`.
    ws = get_settings().workspace_root
    assert not unbound_chat_log_path(ws, cid).exists()


def test_get_lab_chats_empty_when_root_missing(workspace: Path) -> None:
    r = client.get("/lab/chats")
    assert r.status_code == 200
    assert r.json() == []


async def test_get_lab_chats_returns_unbound_chats(workspace: Path) -> None:
    ws = get_settings().workspace_root
    cid = "c_unbroute0001"
    ensure_chat_meta(
        ws, _UNBOUND_SLUG, cid,
        first_user_message="hi", has_attachments=False,
    )
    await append_event(
        ws, _UNBOUND_SLUG, cid, {"type": "user", "text": "hi"},
    )

    r = client.get("/lab/chats")
    assert r.status_code == 200
    body = r.json()
    assert any(c["chat_id"] == cid for c in body)
    entry = next(c for c in body if c["chat_id"] == cid)
    assert entry["label"] == "hi"
    assert entry["kind"] == "chat"
    assert entry["n_events"] == 1
    assert entry["attachment_count"] == 0


async def test_get_lab_chats_events_replays_log(workspace: Path) -> None:
    ws = get_settings().workspace_root
    cid = "c_unbroute0002"
    ensure_chat_meta(
        ws, _UNBOUND_SLUG, cid,
        first_user_message="alpha", has_attachments=False,
    )
    await append_event(
        ws, _UNBOUND_SLUG, cid, {"type": "user", "text": "alpha"},
    )
    await append_event(
        ws, _UNBOUND_SLUG, cid, {"type": "agent_text", "text": "beta"},
    )

    r = client.get(f"/lab/chats/{cid}/events")
    assert r.status_code == 200
    assert r.json() == {
        "events": [
            {"type": "user", "text": "alpha"},
            {"type": "agent_text", "text": "beta"},
        ],
    }


def test_get_lab_chats_events_rejects_bad_chat_id(workspace: Path) -> None:
    r = client.get("/lab/chats/not-a-chat-id/events")
    assert r.status_code == 400


async def test_post_lab_chats_promote_moves_history(workspace: Path) -> None:
    ws = get_settings().workspace_root
    cid = "c_unbroute0003"
    ensure_chat_meta(
        ws, _UNBOUND_SLUG, cid,
        first_user_message="ingest", has_attachments=False,
    )
    await append_event(
        ws, _UNBOUND_SLUG, cid, {"type": "user", "text": "ingest"},
    )
    # An attachment to confirm it moves with the chat.
    att_dir = unbound_chat_attachments_dir(ws, cid)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "scan.pdf").write_bytes(b"%PDF-fake")

    r = client.post(
        f"/lab/chats/{cid}/promote", json={"name": "promote-route"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "promote-route"
    assert body["project_id"].startswith("p_")

    new_slug = body["slug"]
    dst = chats_dir(ws, new_slug) / f"{cid}.jsonl"
    assert dst.exists()
    assert json.loads(dst.read_text().splitlines()[0]) == {
        "type": "user", "text": "ingest",
    }
    assert (chats_dir(ws, new_slug) / cid / "attachments" / "scan.pdf").exists()
    # Unbound slot is gone + tombstoned.
    assert not unbound_chat_log_path(ws, cid).exists()
    assert unbound_chat_tombstone_path(ws, cid).exists()


async def test_delete_lab_chats_tombstones_unbound_chat(workspace: Path) -> None:
    ws = get_settings().workspace_root
    cid = "c_unbroute0004"
    ensure_chat_meta(
        ws, _UNBOUND_SLUG, cid,
        first_user_message="goodbye", has_attachments=False,
    )
    await append_event(
        ws, _UNBOUND_SLUG, cid, {"type": "user", "text": "goodbye"},
    )

    r = client.delete(f"/lab/chats/{cid}")
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": True, "existed": True}

    # Subsequent listing no longer includes the chat.
    listed = client.get("/lab/chats").json()
    assert all(c["chat_id"] != cid for c in listed)
    # Tombstone marker is in place; jsonl is gone.
    assert unbound_chat_tombstone_path(ws, cid).exists()
    assert not unbound_chat_log_path(ws, cid).exists()


def test_delete_unknown_unbound_chat_is_idempotent(workspace: Path) -> None:
    r = client.delete("/lab/chats/c_neverexisted")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["existed"] is False


async def test_chat_id_path_does_not_match_slug_route(workspace: Path) -> None:
    """A chat-id-shaped path under `/lab/chats/` must hit the unbound-chat
    routes, NOT the legacy `GET /lab/chats/{slug}` (which would try to read
    `<chat_id>/chats/` as a project). Route ordering in `chat.py` is
    load-bearing — pin it explicitly so a refactor that reshuffles handlers
    surfaces here."""
    ws = get_settings().workspace_root
    cid = "c_unbroute0005"
    ensure_chat_meta(
        ws, _UNBOUND_SLUG, cid,
        first_user_message="ping", has_attachments=False,
    )
    await append_event(ws, _UNBOUND_SLUG, cid, {"type": "user", "text": "ping"})

    # `/lab/chats/{cid}/events` MUST resolve to the unbound history handler.
    r = client.get(f"/lab/chats/{cid}/events")
    assert r.status_code == 200
    assert r.json() == {"events": [{"type": "user", "text": "ping"}]}
