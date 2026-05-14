import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.chat.log import append_event, ensure_chat_meta
from app.tools.projects import create_project
from app.workspace.paths import chat_meta_path
from app.config import get_settings


client = TestClient(app)


async def test_chat_list_endpoint_returns_sorted_chats(workspace: Path) -> None:
    # `workspace` fixture already points get_settings().workspace_root at a tmp dir.
    ws = get_settings().workspace_root
    pid = (await create_project(ws, name="x"))["slug"]
    for cid, msg, ts in [
        ("c_aaaaaaaaaaaa", "/init x", "2026-05-10T00:00:00+00:00"),
        ("c_bbbbbbbbbbbb", "/extract", "2026-05-12T00:00:00+00:00"),
    ]:
        await append_event(ws, pid, cid, {"type": "user", "text": msg})
        ensure_chat_meta(ws, pid, cid, first_user_message=msg, has_attachments=False)
        p = chat_meta_path(ws, pid, cid)
        d = json.loads(p.read_text())
        d["created_at"] = ts
        p.write_text(json.dumps(d))
    r = client.get(f"/lab/chats/{pid}")
    assert r.status_code == 200
    body = r.json()
    assert [c["chat_id"] for c in body] == ["c_bbbbbbbbbbbb", "c_aaaaaaaaaaaa"]
    assert body[0]["kind"] == "run"
    assert body[0]["label"] == "extract"
    assert body[0]["n_events"] == 1
    assert body[0]["ts_iso"] == "2026-05-12T00:00:00+00:00"


async def test_chat_list_empty_for_project_with_no_chats(workspace: Path) -> None:
    ws = get_settings().workspace_root
    pid = (await create_project(ws, name="x"))["slug"]
    r = client.get(f"/lab/chats/{pid}")
    assert r.status_code == 200
    assert r.json() == []


def test_chat_list_rejects_unsafe_slug() -> None:
    """safe_slug only rejects filesystem-hostile characters (slash / NUL /
    control / `.` / `..`). A NUL injection trips it; `not-a-valid-id` would
    NOT — the slug namespace is intentionally permissive."""
    r = client.get("/lab/chats/bad%00ctrl")
    assert r.status_code == 400


def test_chat_list_returns_empty_for_unknown_slug() -> None:
    """An unknown but valid-shape slug returns 200 with [] — there's no
    project, but the list response is permissive."""
    r = client.get("/lab/chats/not-a-valid-id")
    assert r.status_code == 200
    assert r.json() == []
