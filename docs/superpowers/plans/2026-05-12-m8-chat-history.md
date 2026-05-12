# M8 — Chat History & New-Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (the user's default — see auto-memory `feedback_default_execution_mode.md`) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-chat-per-project model with multiple chats per project, surfaced as a Claude-style "Chat history + New chat" control pair at the top-right of the conversation column, plus the two left-rail slimming tweaks (drop per-row doc-count meta + status dot on the active project; collapse all FS-tree directories except `docs/`).

**Architecture:** Backend grows a chat-list endpoint (`GET /lab/chats/{project_id}`) backed by a directory scan of `chats/c_*.jsonl` plus an extended `{chat_id}.meta.json` sidecar carrying `{label, kind, created_at}` alongside the existing `sdk_session_id`. Meta is written once on chat creation; subsequent writes (e.g. session-id updates) merge rather than overwrite. The frontend `useChat` store gains `chatsByProject` (server-authoritative, in-memory) plus `listChats / switchChat / newChat` actions, and the localStorage key migrates from `emerge.chatId.<pid>` (single) to `emerge.activeChatId.<pid>`. A new `ConvHeader` component renders the floating chips + popover, ported verbatim from the design reference. M7.1's reload-restore behavior (chat events hydrate from the server log on project entry) is preserved — switching chats simply re-runs the same hydrate against a different `chat_id`.

**Tech Stack:** Backend — FastAPI, pydantic v2, `uv` + `pytest`. Frontend — Vite + React 19 + TypeScript + Zustand + Tailwind v3 (CSS-var tokens only, **no Tailwind color classes**) + Playwright (e2e) + Vitest + RTL (unit).

**Hard rules in play (from `CLAUDE.md`):** UI vocabulary is task-type-agnostic — chrome (chips, popover header, empty state, button copy) uses generic verbs `init | run | tune | review | publish | ingest | chat`; **never** `extract` / `improve` / `invoice` / `document` in chrome. No new write path may bypass `chat/redactor.py` — we generate **no summary** (revision 2 dropped it), so the chat-list path stores nothing user-message-derived except `label`/`kind`, both of which are derived from the *already-redacted-on-append* first user line; the planner has confirmed no additional redactor pass is required for the list endpoint (it returns metadata, not chat content). No image few-shot, no bbox — irrelevant here. `schema.json` only via `write_schema` tool — irrelevant here.

---

## File Structure

### Backend (create / modify)
- **Modify** `backend/app/chat/log.py` — add chat-meta read/write (merge-aware), `ensure_chat_meta`, `derive_chat_kind`, `derive_chat_label`, `list_chats`; rewrite `read_chat_session_id` / `write_chat_session_id` to go through the merge-aware meta helpers.
- **Modify** `backend/app/chat/service.py` — call `ensure_chat_meta` on the first turn of a chat (right after the `{"type":"user"}` append).
- **Modify** `backend/app/api/routes/chat.py` — add `GET /lab/chats/{project_id}` returning the chat list.
- **Modify** `backend/app/tools/projects.py` — `list_projects` returns an additive `status: "live" | "draft" | "empty"` per project.
- **Modify** `backend/tests/e2e_seed.py` — seed one chat log + meta sidecar so the e2e chat-history spec has data.
- **Create** `backend/tests/unit/test_chat_meta.py` — `derive_chat_kind` / `derive_chat_label` mapping, `ensure_chat_meta` idempotency, merge-aware session-id writes, `list_chats` sorting/empty.
- **Create** `backend/tests/integration/test_lab_chat_list.py` — `GET /lab/chats/{project_id}` happy path + malformed-id 400.
- **Modify** `backend/tests/integration/test_lab_projects.py` — assert the new `status` field.

### Frontend (create / modify)
- **Modify** `frontend/src/lib/api.ts` — add `ChatSummary` interface + `getChatList(projectId)`; add `status?: 'live'|'draft'|'empty'` to `Project`.
- **Modify** `frontend/src/stores/chat.ts` — localStorage key migration; `chatsByProject` state; `listChats / switchChat / newChat` actions; refresh the list after a completed send; `enterProject` reads the new key.
- **Modify** `frontend/src/index.css` — append `.conv-hd`, `.hist-pop`, and the `.conv > .conv-scroll{padding-top:54px}` rule, copied verbatim from the design `index.html`.
- **Create** `frontend/src/components/Chat/ConvHeader.tsx` — the two floating chips + history popover, ported from `pieces.jsx`.
- **Modify** `frontend/src/components/Chat/ChatPanel.tsx` — mount `<ConvHeader>` when a real project is selected.
- **Modify** `frontend/src/components/Spine/FSSpine.tsx` — drop the `meta` span; render the status dot on the active project row; group the FS tree by directory with a `docs/`-only-open default.
- **Modify** `frontend/src/components/Spine/spine.css` — add `.fs .proj .status-dot` and a `cursor:default` on `.branch.dir`.
- **Create** `frontend/src/components/Chat/ConvHeader.test.tsx` — render + interaction unit test.
- **Modify** `frontend/tests/unit/chat-hydrate.test.ts` — extend with `listChats` / `switchChat` race-safety / `newChat` / localStorage-migration cases.
- **Create** `frontend/tests/e2e/chat-history.spec.ts` — open popover, switch chats, new-chat → EmptyHero, status dot visible, FS-tree collapse default.

### Docs
- **Modify** `docs/superpowers/plans/ROADMAP.md` — add the M8 row + "what it delivers" section.
- **Modify** `docs/design-decisions.md` — resolve the 2026-05-11 "Chat history survives page reload" entry (it's the predecessor, superseded in spirit by multi-chat).

---

## Task 1: Backend — chat-meta module (kind/label derivation, merge-aware sidecar, `list_chats`)

**Files:**
- Modify: `backend/app/chat/log.py`
- Test: `backend/tests/unit/test_chat_meta.py` (create)

The current sidecar (`{chat_id}.meta.json`) holds only `sdk_session_id`. We extend it with `{label, kind, created_at}`. All writes must be merge-aware so a `write_chat_session_id` call doesn't clobber `label`/`kind` (and vice-versa).

- [ ] **Step 1: Write the failing test** — `backend/tests/unit/test_chat_meta.py`

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_chat_meta.py -v`
Expected: FAIL — `ImportError: cannot import name 'derive_chat_kind' from 'app.chat.log'` (etc.).

- [ ] **Step 3: Implement in `backend/app/chat/log.py`**

Add these imports at the top (keep the existing ones):

```python
import json
import re
from datetime import datetime, timezone
```

(`json` and `asyncio` are already imported; add `re` and the `datetime` import. Keep `from pathlib import Path` and the existing `from app.workspace.atomic import atomic_write_json` / `from app.workspace.paths import chat_meta_path, chats_dir`.)

Add the kind/label derivation and meta helpers. Place them *after* `append_event` / `read_chat_events`, and **replace** the existing `read_chat_session_id` / `write_chat_session_id` with the merge-aware versions below:

```python
# ── chat metadata sidecar ({chat_id}.meta.json) ───────────────────────────
# Holds {label, kind, created_at} (set once on chat creation) alongside the
# resumable {sdk_session_id} (rewritten per turn). All writes merge — never
# clobber the other half. No `summary` is stored (design revision 2 dropped
# it), so nothing in this path needs the chat redactor.

_SLASH_CMD_KIND = {
    "init": "init",
    "extract": "run",
    "eval": "run",
    "improve": "tune",
    "publish": "publish",
    "review": "review",
}
_CMD_RE = re.compile(r"^/([a-z][a-z0-9_-]*)\b")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_chat_kind(first_user_message: str, *, has_attachments: bool) -> str:
    """Generic-verb kind for a chat. Attachments on turn 1 → 'ingest'. Else the
    slash-command map (slash-cmd → generic verb, intentionally many-to-one), else
    'chat'. Reserve doc-extraction nouns for content text, not this taxonomy."""
    if has_attachments:
        return "ingest"
    m = _CMD_RE.match((first_user_message or "").strip())
    if m:
        return _SLASH_CMD_KIND.get(m.group(1), "chat")
    return "chat"


def derive_chat_label(first_user_message: str) -> str:
    """Short (<=40 char) present-tense label. Strips a leading `/cmd`."""
    s = (first_user_message or "").strip()
    m = _CMD_RE.match(s)
    if m:
        s = s[m.end():].strip()
    if not s:
        # Bare `/cmd` with no args → use the command word; truly empty → 'untitled'.
        m2 = _CMD_RE.match((first_user_message or "").strip())
        return m2.group(1) if m2 else "untitled"
    return s[:40].rstrip()


def read_chat_meta(workspace: Path, project_id: str, chat_id: str) -> dict[str, Any]:
    """Whole meta dict ({} if missing/unreadable)."""
    meta_path = chat_meta_path(workspace, project_id, chat_id)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_chat_meta(workspace: Path, project_id: str, chat_id: str, data: dict[str, Any]) -> None:
    chats_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(chat_meta_path(workspace, project_id, chat_id), data)


def ensure_chat_meta(
    workspace: Path,
    project_id: str,
    chat_id: str,
    *,
    first_user_message: str,
    has_attachments: bool,
) -> None:
    """Set {label, kind, created_at} once. Idempotent: a second call (later turn)
    does not overwrite an already-set kind/label/created_at."""
    meta = read_chat_meta(workspace, project_id, chat_id)
    changed = False
    if "kind" not in meta:
        meta["kind"] = derive_chat_kind(first_user_message, has_attachments=has_attachments)
        changed = True
    if "label" not in meta:
        meta["label"] = derive_chat_label(first_user_message)
        changed = True
    if "created_at" not in meta:
        meta["created_at"] = _now_iso()
        changed = True
    if changed:
        _write_chat_meta(workspace, project_id, chat_id, meta)


def read_chat_session_id(workspace: Path, project_id: str, chat_id: str) -> str | None:
    """Return the persisted SDK session id for resuming, or None."""
    sid = read_chat_meta(workspace, project_id, chat_id).get("sdk_session_id")
    return sid if isinstance(sid, str) and sid else None


def write_chat_session_id(
    workspace: Path,
    project_id: str,
    chat_id: str,
    session_id: str | None,
) -> None:
    """Merge the SDK session id into the meta sidecar (None clears just that key).
    If clearing leaves the sidecar empty, the file is removed; otherwise the
    {label, kind, created_at} half is preserved."""
    meta = read_chat_meta(workspace, project_id, chat_id)
    if session_id is None:
        meta.pop("sdk_session_id", None)
        meta_path = chat_meta_path(workspace, project_id, chat_id)
        if not meta:
            try:
                meta_path.unlink()
            except FileNotFoundError:
                pass
            return
        _write_chat_meta(workspace, project_id, chat_id, meta)
        return
    meta["sdk_session_id"] = session_id
    _write_chat_meta(workspace, project_id, chat_id, meta)


def list_chats(workspace: Path, project_id: str) -> list[dict[str, Any]]:
    """All chats for a project, newest first. Source of truth = directory scan of
    chats/c_*.jsonl plus the meta sidecar; legacy logs (no sidecar) fall back to
    deriving kind/label from line 1 and ts from file mtime. Returns [] if the
    project has no chats dir."""
    cdir = chats_dir(workspace, project_id)
    if not cdir.exists():
        return []
    out: list[dict[str, Any]] = []
    for log_path in cdir.glob("c_*.jsonl"):
        chat_id = log_path.stem
        events = read_chat_events(workspace, project_id, chat_id)
        meta = read_chat_meta(workspace, project_id, chat_id)
        kind = meta.get("kind")
        label = meta.get("label")
        ts_iso = meta.get("created_at")
        if not kind or not label or not ts_iso:
            first_user = next(
                (e.get("text", "") for e in events if e.get("type") == "user"), ""
            )
            kind = kind or derive_chat_kind(first_user, has_attachments=False)
            label = label or derive_chat_label(first_user)
            if not ts_iso:
                try:
                    ts_iso = datetime.fromtimestamp(
                        log_path.stat().st_mtime, timezone.utc
                    ).isoformat()
                except OSError:
                    ts_iso = _now_iso()
        out.append({
            "chat_id": chat_id,
            "label": label,
            "kind": kind,
            "ts_iso": ts_iso,
            "n_events": len(events),
        })
    out.sort(key=lambda c: c["ts_iso"], reverse=True)
    return out
```

Remove the now-obsolete top-of-file `from pathlib import Path` only if it becomes unused — it is still used (`read_chat_events` signature), so keep it. Ensure `from typing import Any` is present (it is).

- [ ] **Step 4: Run the new tests**

Run: `cd backend && uv run pytest tests/unit/test_chat_meta.py -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Run the existing chat-log tests to check the session-id refactor didn't regress**

Run: `cd backend && uv run pytest tests/unit/test_chat_log.py -v`
Expected: PASS — in particular `test_session_id_sidecar_roundtrip` (sidecar with only `sdk_session_id` is deleted on clear) and `test_read_chat_session_id_bad_json` still pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/chat/log.py backend/tests/unit/test_chat_meta.py
git commit -m "feat(chat): chat-meta sidecar (label/kind/created_at) + merge-aware writes + list_chats"
```

---

## Task 2: Backend — wire `ensure_chat_meta` into `chat_turn` + `GET /lab/chats/{project_id}` route

**Files:**
- Modify: `backend/app/chat/service.py:154-160`
- Modify: `backend/app/api/routes/chat.py`
- Test: `backend/tests/integration/test_lab_chat_list.py` (create)

- [ ] **Step 1: Write the failing integration test** — `backend/tests/integration/test_lab_chat_list.py`

```python
import json

from fastapi.testclient import TestClient

from app.main import app
from app.chat.log import append_event, ensure_chat_meta
from app.tools.projects import create_project
from app.workspace.paths import chat_meta_path
from app.config import get_settings


client = TestClient(app)


async def test_chat_list_endpoint_returns_sorted_chats(workspace: Path) -> None:  # noqa: F821
    # `workspace` fixture already points get_settings().workspace_root at a tmp dir.
    ws = get_settings().workspace_root
    pid = await create_project(ws, name="x")
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


async def test_chat_list_empty_for_project_with_no_chats(workspace: Path) -> None:  # noqa: F821
    ws = get_settings().workspace_root
    pid = await create_project(ws, name="x")
    r = client.get(f"/lab/chats/{pid}")
    assert r.status_code == 200
    assert r.json() == []


def test_chat_list_rejects_malformed_project_id() -> None:
    # `safe_project_id` validation — matches the existing per-chat route's behavior.
    r = client.get("/lab/chats/not-a-valid-id")
    assert r.status_code == 400
```

> Note: match the import style of the sibling tests in `backend/tests/integration/` for the `workspace` fixture (it's a `conftest.py` fixture; check `test_lab_projects.py` for whether it's `async def` + `workspace: Path` or a context-managed `client`). Mirror exactly what those files do — the snippet above uses `get_settings().workspace_root` after the fixture has repointed it, which is the pattern in `test_lab_eval.py`. Adjust if `test_lab_projects.py` uses a different convention.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_lab_chat_list.py -v`
Expected: FAIL — `GET /lab/chats/{project_id}` 404 (route not yet defined), so `r.status_code == 200` assertions fail.

- [ ] **Step 3: Add the route to `backend/app/api/routes/chat.py`**

Add `list_chats` to the existing import line:

```python
from app.chat.log import list_chats, read_chat_events
```

Add the new route (place it above the existing `/lab/chats/{project_id}/{chat_id}` route so FastAPI's path matching prefers the more specific 2-segment route for that one — FastAPI matches by registration order; the 1-segment `/lab/chats/{project_id}` and 2-segment `/lab/chats/{project_id}/{chat_id}` don't collide, but register the list route first for clarity):

```python
@router.get("/lab/chats/{project_id}")
async def lab_chat_list(project_id: str) -> list[dict[str, Any]]:
    safe_project_id(project_id)
    workspace_root = get_settings().workspace_root
    return list_chats(workspace_root, project_id)
```

- [ ] **Step 4: Wire `ensure_chat_meta` into `chat_turn`** — `backend/app/chat/service.py`

Add `ensure_chat_meta` to the import on line 22:

```python
from app.chat.log import append_event, ensure_chat_meta, read_chat_session_id, write_chat_session_id
```

In `chat_turn`, right after the existing first-`append_event` (the `{"type": "user", "text": user_message}` one, ~line 154-159) and before `yield sse_event("user_acknowledged", ...)`, add:

```python
        ensure_chat_meta(
            self.workspace,
            project_id,
            chat_id,
            first_user_message=user_message,
            has_attachments=bool(attachments),
        )
```

This is a no-op on every turn after the first (the meta file already has `kind`/`label`/`created_at`).

- [ ] **Step 5: Run the integration test + the chat-session-continuity test (the meta write must not break resume)**

Run: `cd backend && uv run pytest tests/integration/test_lab_chat_list.py tests/integration/test_chat_session_continuity.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/chat.py backend/app/chat/service.py backend/tests/integration/test_lab_chat_list.py
git commit -m "feat(chat): GET /lab/chats/{pid} chat-list endpoint; set chat meta on first turn"
```

---

## Task 3: Backend — `status` field on `GET /lab/projects`

**Files:**
- Modify: `backend/app/tools/projects.py` (`list_projects`)
- Test: `backend/tests/integration/test_lab_projects.py` (extend)

Derivation (additive — no FE breakage if rolled back): `live` if `active_version_id` is set; else `draft` if `schema.json` exists and is a non-empty list; else `empty`. (`schema.json` is always created as `[]` by `create_project`, so "draft" means it has at least one field.)

- [ ] **Step 1: Add a failing assertion to `backend/tests/integration/test_lab_projects.py`**

Append a new test (mirror the file's existing fixture/style):

```python
async def test_list_projects_includes_status(workspace: Path) -> None:  # noqa: F821
    from app.tools.projects import list_projects
    from app.tools.schema import write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    ws = workspace  # or get_settings().workspace_root — match this file's convention
    p_empty = await create_project(ws, name="empty-one")
    p_draft = await create_project(ws, name="draft-one")
    await write_schema(
        ws, p_draft,
        [SchemaField(name="f", type=FieldType.STRING, description="d")],
        reason="t", allow_structural=True,
    )
    rows = {r["project_id"]: r for r in await list_projects(ws)}
    assert rows[p_empty]["status"] == "empty"
    assert rows[p_draft]["status"] == "draft"
    # 'live' requires an active_version_id — set it directly on the blob.
    from app.tools.projects import update_project
    await update_project(ws, p_draft, {"active_version_id": "v1"})
    rows = {r["project_id"]: r for r in await list_projects(ws)}
    assert rows[p_draft]["status"] == "live"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v -k status`
Expected: FAIL — `KeyError: 'status'`.

- [ ] **Step 3: Implement in `backend/app/tools/projects.py`**

In `list_projects`, replace the per-project append block:

```python
        blob = json.loads(pj.read_text())
        out.append({"project_id": child.name, **blob})
```

with:

```python
        blob = json.loads(pj.read_text())
        out.append({
            "project_id": child.name,
            "status": _project_status(child, blob),
            **blob,
        })
```

and add the helper near the top of the file (after `_now_iso`):

```python
def _project_status(pdir: Path, blob: dict[str, Any]) -> str:
    if blob.get("active_version_id"):
        return "live"
    sp = pdir / "schema.json"
    if sp.exists():
        try:
            fields = json.loads(sp.read_text())
            if isinstance(fields, list) and len(fields) > 0:
                return "draft"
        except (json.JSONDecodeError, OSError):
            pass
    return "empty"
```

> Note: spreading `**blob` *after* `"status"` means a stray `status` key inside `project.json` would win — but `project.json` never contains one, and putting `status` first keeps the derived value authoritative if a future migration adds one. Leave it before `**blob`.

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest tests/integration/test_lab_projects.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tools/projects.py backend/tests/integration/test_lab_projects.py
git commit -m "feat(projects): additive status field (live/draft/empty) on GET /lab/projects"
```

---

## Task 4: Frontend — `api.ts` (ChatSummary + getChatList + Project.status)

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the `status` field to `Project` and the `ChatSummary` type + fetcher**

In `frontend/src/lib/api.ts`, extend the `Project` interface:

```typescript
export interface Project {
  project_id: string
  name: string
  project_type: string
  active_version_id: string | null
  status?: 'live' | 'draft' | 'empty'
}
```

And add (next to `getChatEvents`, which already has the "permissive by design" comment — match that tone):

```typescript
export interface ChatSummary {
  chat_id: string
  label: string
  kind: string
  ts_iso: string
  n_events: number
}

// Chat list for the conv-header history popover. Permissive — any failure
// degrades to an empty list, never throws into a render.
export async function getChatList(projectId: string): Promise<ChatSummary[]> {
  try {
    const r = await fetch(`/lab/chats/${projectId}`)
    if (!r.ok) {
      if (r.status !== 404) console.warn('getChatList failed', r.status)
      return []
    }
    return (await r.json()) as ChatSummary[]
  } catch (err) {
    console.warn('getChatList threw', err)
    return []
  }
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc -b --noEmit` (or `npm run build` — but `tsc -b` is faster for a quick check)
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): ChatSummary type + getChatList; Project.status field"
```

---

## Task 5: Frontend — `stores/chat.ts` (localStorage migration, chatsByProject, listChats/switchChat/newChat)

**Files:**
- Modify: `frontend/src/stores/chat.ts`
- Test: `frontend/tests/unit/chat-hydrate.test.ts` (extend)

Keep the existing in-flight-tail race-safety pattern (`prefixLen` snapshot + `chatId`/`loadedProjectId` re-check before applying a hydrate). `switchChat` is structurally the same as `enterProject`'s switch branch, just keyed on an explicit `chatId` instead of `chatIdFor(projectId)`.

- [ ] **Step 1: Write the failing tests** — append to `frontend/tests/unit/chat-hydrate.test.ts`

```typescript
import { getChatList } from '../../src/lib/api'  // add to existing imports if not present

describe('localStorage key migration', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null })
    vi.restoreAllMocks()
  })

  it('chatIdFor migrates emerge.chatId.<pid> → emerge.activeChatId.<pid> on first read', () => {
    localStorage.setItem('emerge.chatId.p_old', 'c_legacy00001')
    expect(chatIdFor('p_old')).toBe('c_legacy00001')
    expect(localStorage.getItem('emerge.activeChatId.p_old')).toBe('c_legacy00001')
    // Old key is left in place for one session (no UI to clear it).
    expect(localStorage.getItem('emerge.chatId.p_old')).toBe('c_legacy00001')
  })

  it('chatIdFor prefers the new key when both exist', () => {
    localStorage.setItem('emerge.chatId.p_x', 'c_old000000001')
    localStorage.setItem('emerge.activeChatId.p_x', 'c_new000000001')
    expect(chatIdFor('p_x')).toBe('c_new000000001')
  })
})

describe('listChats', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: null, chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('fetches and stores the list under chatsByProject[pid]', async () => {
    const list = [
      { chat_id: 'c_aaaaaaaaaaaa', label: 'extract', kind: 'run', ts_iso: '2026-05-12T09:00:00+00:00', n_events: 4 },
    ]
    vi.spyOn(api, 'getChatList').mockResolvedValue(list)
    await useChat.getState().listChats('p_1')
    expect(useChat.getState().chatsByProject['p_1']).toEqual(list)
  })

  it('a failed fetch leaves chatsByProject[pid] = [] (never throws)', async () => {
    vi.spyOn(api, 'getChatList').mockResolvedValue([])
    await useChat.getState().listChats('p_1')
    expect(useChat.getState().chatsByProject['p_1']).toEqual([])
  })
})

describe('switchChat', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: 'p_a', chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('persists the new active chat id, clears events, hydrates from the server', async () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([{ type: 'agent_text', text: 'from chat 2' }])
    useChat.setState({ events: [{ type: 'user', text: 'stale' }], chatId: 'c_old000000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_new000000001')
    // synchronous
    const after = useChat.getState()
    expect(after.chatId).toBe('c_new000000001')
    expect(after.events).toEqual([])
    expect(localStorage.getItem('emerge.activeChatId.p_a')).toBe('c_new000000001')
    // microtask: hydrated
    await Promise.resolve(); await Promise.resolve()
    expect(spy).toHaveBeenCalledWith('p_a', 'c_new000000001')
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'from chat 2' }])
  })

  it('switching to the already-active chat is a no-op (no clear, no fetch)', () => {
    const spy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'agent_text', text: 'kept' }], chatId: 'c_same00000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_same00000001')
    expect(useChat.getState().events).toEqual([{ type: 'agent_text', text: 'kept' }])
    expect(spy).not.toHaveBeenCalled()
  })

  it('switch race: a hydrate in-flight when the user switches again is dropped', async () => {
    let resolveA!: (v: unknown[]) => void
    const deferredA = new Promise<unknown[]>(res => { resolveA = res })
    vi.spyOn(api, 'getChatEvents')
      .mockImplementationOnce(() => deferredA)
      .mockImplementationOnce(() => Promise.resolve([]))
    useChat.setState({ events: [], chatId: 'c_orig00000001', loadedProjectId: 'p_a' })
    useChat.getState().switchChat('p_a', 'c_aaa000000001')
    useChat.getState().switchChat('p_a', 'c_bbb000000001')
    resolveA([{ type: 'user', text: 'chat-A history' }])
    await Promise.resolve(); await Promise.resolve()
    const after = useChat.getState()
    expect(after.chatId).toBe('c_bbb000000001')
    expect(after.events.some(e => e.type === 'user' && e.text === 'chat-A history')).toBe(false)
  })
})

describe('newChat', () => {
  beforeEach(() => {
    localStorage.clear()
    useChat.setState({ events: [], busy: false, chatId: 'c_initial', loadedProjectId: 'p_a', chatsByProject: {} })
    vi.restoreAllMocks()
  })

  it('mints a fresh id, persists it as active, clears events, does NOT touch the server', () => {
    const evSpy = vi.spyOn(api, 'getChatEvents').mockResolvedValue([])
    const listSpy = vi.spyOn(api, 'getChatList').mockResolvedValue([])
    useChat.setState({ events: [{ type: 'user', text: 'old chat' }], chatId: 'c_old000000001', loadedProjectId: 'p_a' })
    useChat.getState().newChat('p_a')
    const after = useChat.getState()
    expect(after.chatId).toMatch(/^c_[0-9a-f]{12}$/)
    expect(after.chatId).not.toBe('c_old000000001')
    expect(after.events).toEqual([])
    expect(after.loadedProjectId).toBe('p_a')
    expect(localStorage.getItem('emerge.activeChatId.p_a')).toBe(after.chatId)
    expect(evSpy).not.toHaveBeenCalled()
    expect(listSpy).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run tests/unit/chat-hydrate.test.ts`
Expected: FAIL — `useChat.getState().listChats` / `switchChat` / `newChat` are not functions; `chatsByProject` is undefined.

- [ ] **Step 3: Implement in `frontend/src/stores/chat.ts`**

Add the new key prefix and migration. Replace the top constants + `_readChatId`/`_writeChatId`/`chatIdFor` block:

```typescript
const ACTIVE_CHAT_ID_KEY_PREFIX = 'emerge.activeChatId.'
const LEGACY_CHAT_ID_KEY_PREFIX = 'emerge.chatId.'   // pre-M8 single-chat key

// Process-lifetime fallback when localStorage is unavailable (SSR / incognito).
const _memChatIds = new Map<string, string>()

function _readChatId(projectId: string): string | null {
  try {
    const fresh = localStorage.getItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId)
    if (fresh) return fresh
    // Migration: copy the legacy single-chat key forward (leave the old key in
    // place for one session — no UI clears it; a rollback to the pre-M8 build
    // keeps working).
    const legacy = localStorage.getItem(LEGACY_CHAT_ID_KEY_PREFIX + projectId)
    if (legacy) {
      localStorage.setItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId, legacy)
      return legacy
    }
    return null
  } catch {
    return _memChatIds.get(projectId) ?? null
  }
}

function _writeChatId(projectId: string, chatId: string): void {
  try {
    localStorage.setItem(ACTIVE_CHAT_ID_KEY_PREFIX + projectId, chatId)
  } catch {
    _memChatIds.set(projectId, chatId)
  }
}

/** Per-project, persisted *active* chat id. Mints + persists one on first access. */
function chatIdFor(projectId: string): string {
  const existing = _readChatId(projectId)
  if (existing) return existing
  const fresh = newChatId()
  _writeChatId(projectId, fresh)
  return fresh
}
```

Add `getChatList` and `ChatSummary` to the api import:

```typescript
import { getChatEvents, getChatList, type ChatSummary } from '../lib/api'
```

Extend the `State` interface:

```typescript
interface State {
  chatId: string
  events: ChatEvent[]
  busy: boolean
  loadedProjectId: string | null
  chatsByProject: Record<string, ChatSummary[]>
  send: (projectId: string, message: string, attachments?: { filename: string }[]) => Promise<void>
  enterProject: (projectId: string) => void
  listChats: (projectId: string) => Promise<void>
  switchChat: (projectId: string, chatId: string) => void
  newChat: (projectId: string) => void
  lastUserMessage: () => string | null
  hasRecentToolError: () => boolean
}
```

Add `chatsByProject: {}` to the store's initial state (right after `loadedProjectId: null,`).

Add the three actions. Place `listChats` / `switchChat` / `newChat` after `enterProject`:

```typescript
  listChats: async (projectId) => {
    if (projectId === 'p_unset') return
    const list = await getChatList(projectId)
    set(s => ({ chatsByProject: { ...s.chatsByProject, [projectId]: list } }))
  },
  switchChat: (projectId, chatId) => {
    if (projectId === 'p_unset') return
    if (chatId === get().chatId) return   // already active → no-op
    _writeChatId(projectId, chatId)
    set({ loadedProjectId: projectId, chatId, events: [], busy: false })
    const prefixLen = get().events.length
    void (async () => {
      const reduced = reduceEvents(await getChatEvents(projectId, chatId))
      set(s => {
        if (s.chatId !== chatId || s.loadedProjectId !== projectId) return s
        if (s.events.length === prefixLen) return { events: reduced }
        return { events: [...reduced, ...s.events] }
      })
    })()
  },
  newChat: (projectId) => {
    if (projectId === 'p_unset') return
    const fresh = newChatId()
    _writeChatId(projectId, fresh)
    set({ loadedProjectId: projectId, chatId: fresh, events: [], busy: false })
    // No server write — the chat comes into being on the first /lab/chat POST,
    // same as today. The list will pick it up after that turn completes.
  },
```

In `enterProject`'s switch branch, after the existing hydrate is dispatched, also kick off a list refresh so the popover is warm when first opened. Add right after the `void (async () => { ... })()` IIFE in that branch:

```typescript
    void get().listChats(projectId)
```

In `send`, after the SSE loop finishes (in the `finally` block, after `set({ busy: false })`), refresh the chat list so a brand-new chat shows up in the popover:

```typescript
    } finally {
      set({ busy: false })
      if (projectId !== 'p_unset') void get().listChats(projectId)
    }
```

Add `switchChat` and `newChat` (and keep `chatIdFor`) to `_testUtils` if helpful — `chatIdFor` is already exported there; that's enough for the migration test (`switchChat`/`newChat` are exercised via `useChat.getState()`).

- [ ] **Step 4: Run the chat-store tests**

Run: `cd frontend && npx vitest run tests/unit/chat-hydrate.test.ts`
Expected: PASS — including the existing `enterProject` / `reduceEvents` / `chatIdFor` cases (the migration only *adds* a fallback; the "mints a fresh id when none exists" case still passes because both keys are absent).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/chat.ts frontend/tests/unit/chat-hydrate.test.ts
git commit -m "feat(chat-store): multi-chat — chatsByProject + listChats/switchChat/newChat; activeChatId key migration"
```

---

## Task 6: Frontend — port the conv-header / history-popover CSS

**Files:**
- Modify: `frontend/src/index.css`

Copy the rules verbatim from `docs/design/emerge-api/project/index.html` lines 109-135 — **do not** translate to Tailwind utilities (CLAUDE.md: no Tailwind color classes; the tokens used here all already exist in `frontend/src/theme/tokens.css`). One adjustment: `index.css` already has `.conv-scroll{...}` (no `padding-top`), so add the `.conv > .conv-scroll{padding-top:54px}` rule as a *separate* selector (more specific) rather than editing the base `.conv-scroll`.

- [ ] **Step 1: Append the block to `frontend/src/index.css`**

Add after the existing `.conv-inner{...}` line (and before the `/* ── Turn ── */` section):

```css
/* ── conv header — Claude-style chat history + new buttons (floating, top-right) ── */
.conv-hd{position:absolute;top:10px;right:14px;z-index:8;display:flex;gap:4px;align-items:center}
.conv-hd .chip{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:7px;color:var(--ink-3);background:rgba(253,253,252,.65);border:1px solid transparent;cursor:default;transition:background .12s, color .12s, border-color .12s;position:relative}
.conv-hd .chip:hover{background:var(--paper-2);color:var(--ink);border-color:var(--rule-soft)}
.conv-hd .chip.on{background:var(--paper-3);color:var(--ink);border-color:var(--rule)}
.conv-hd .chip svg{display:block}
.conv-hd .tip{position:absolute;top:36px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--paper);font-family:var(--mono);font-size:10.5px;padding:3px 8px;border-radius:4px;white-space:nowrap;opacity:0;pointer-events:none;transition:opacity .12s;letter-spacing:.02em}
.conv-hd .chip:hover .tip{opacity:1;transition-delay:.35s}

/* history popover */
.hist-pop{position:absolute;top:46px;right:14px;width:280px;max-height:60vh;background:#FDFDFC;border:1px solid var(--rule);border-radius:8px;box-shadow:0 10px 32px rgba(31,27,20,.10);z-index:9;display:flex;flex-direction:column;animation:histIn .14s ease-out;overflow:hidden}
@keyframes histIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
.hist-pop .h-hd{display:flex;align-items:baseline;gap:8px;padding:9px 12px 7px;border-bottom:1px solid var(--rule-soft)}
.hist-pop .h-hd .lab{font-family:var(--mono);font-size:10.5px;color:var(--ink-4);text-transform:uppercase;letter-spacing:.1em}
.hist-pop .h-hd .scope{margin-left:auto;font-family:var(--mono);font-size:10.5px;color:var(--ink-3)}
.hist-pop .h-list{overflow-y:auto;padding:4px;display:flex;flex-direction:column;gap:0}
.hist-pop .h-row{display:flex;align-items:baseline;gap:8px;padding:6px 8px;border-radius:5px;border:1px solid transparent;cursor:default}
.hist-pop .h-row:hover{background:var(--paper-2)}
.hist-pop .h-row.active{background:var(--ochre-soft);border-color:transparent}
.hist-pop .h-row .kind{font-family:var(--mono);font-size:9.5px;color:var(--ink-4);text-transform:uppercase;letter-spacing:.06em;flex-shrink:0;width:54px}
.hist-pop .h-row.active .kind{color:var(--ochre-2)}
.hist-pop .h-row .lbl{font-family:var(--serif);font-size:13px;color:var(--ink);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:.005em}
.hist-pop .h-row .ts{font-family:var(--mono);font-size:10px;color:var(--ink-5);font-variant-numeric:tabular-nums;flex-shrink:0}
.hist-pop .h-empty{font-family:var(--serif);font-style:italic;font-size:13px;color:var(--ink-4);padding:14px;text-align:center}

/* push conv-scroll top padding so it doesn't sit under the floating buttons */
.conv > .conv-scroll{padding-top:54px}
```

> Token sanity check: `--ochre-soft`, `--ochre-2`, `--ink`/`--ink-3`/`--ink-4`/`--ink-5`, `--paper`/`--paper-2`/`--paper-3`, `--rule`/`--rule-soft`, `--mono`/`--serif` must all exist in `frontend/src/theme/tokens.css`. They do (the design `index.html` and the existing `index.css` both use them). If `npx tsc`/build flags an unknown token, stop — do not invent one.

- [ ] **Step 2: Build to confirm CSS parses**

Run: `cd frontend && npm run build`
Expected: PASS (no CSS syntax error).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "style(chat): port conv-header + history-popover CSS from design handoff"
```

---

## Task 7: Frontend — `ConvHeader` component

**Files:**
- Create: `frontend/src/components/Chat/ConvHeader.tsx`
- Test: `frontend/src/components/Chat/ConvHeader.test.tsx` (create)

Port the JSX from `docs/design/emerge-api/project/pieces.jsx` lines 165-226 (the `ConvHeader` + popover), converted JS → TSX. Differences from the reference: the reference reads `window.SESSIONS`; we take `chats: ChatSummary[]` as a prop. The reference's `ConvHeader` only had `onNew`; we add `onSwitch` and `onOpen`. The active row is the one whose `chat_id === currentChatId`. Timestamps come as ISO strings → format to a short label.

- [ ] **Step 1: Write the failing test** — `frontend/src/components/Chat/ConvHeader.test.tsx`

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import ConvHeader from './ConvHeader'
import type { ChatSummary } from '../../lib/api'

const CHATS: ChatSummary[] = [
  { chat_id: 'c_aaaaaaaaaaaa', label: 'tune weak fields', kind: 'tune', ts_iso: '2026-05-12T14:08:00+00:00', n_events: 12 },
  { chat_id: 'c_bbbbbbbbbbbb', label: 'run batch', kind: 'run', ts_iso: '2026-05-12T14:02:00+00:00', n_events: 5 },
]

describe('ConvHeader', () => {
  it('renders two chips and no popover initially', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByLabelText('Chat history')).toBeInTheDocument()
    expect(screen.getByLabelText('New chat')).toBeInTheDocument()
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('opens the popover on history-chip click, calls onOpen, lists rows, highlights the active one', () => {
    const onOpen = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={onOpen} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(onOpen).toHaveBeenCalled()
    expect(screen.getByText('history')).toBeInTheDocument()
    expect(screen.getByText('us-invoice')).toBeInTheDocument()
    expect(screen.getByText('tune weak fields')).toBeInTheDocument()
    expect(screen.getByText('run batch')).toBeInTheDocument()
    const activeRow = screen.getByText('tune weak fields').closest('.h-row')
    expect(activeRow).toHaveClass('active')
  })

  it('clicking a row calls onSwitch with that chat id and closes the popover', () => {
    const onSwitch = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={vi.fn()} onSwitch={onSwitch} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    fireEvent.click(screen.getByText('run batch'))
    expect(onSwitch).toHaveBeenCalledWith('c_bbbbbbbbbbbb')
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('clicking the new-chat chip calls onNew', () => {
    const onNew = vi.fn()
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_aaaaaaaaaaaa" chats={CHATS} onNew={onNew} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('New chat'))
    expect(onNew).toHaveBeenCalled()
  })

  it('shows the empty state when there are no chats', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={[]} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('No sessions yet.')).toBeInTheDocument()
  })

  it('Escape closes the popover', () => {
    render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('history')).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })

  it('closes the popover when activeProject changes', () => {
    const { rerender } = render(<ConvHeader activeProject="us-invoice" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByLabelText('Chat history'))
    expect(screen.getByText('history')).toBeInTheDocument()
    rerender(<ConvHeader activeProject="contracts" currentChatId="c_x" chats={CHATS} onNew={vi.fn()} onSwitch={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.queryByText('history')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/Chat/ConvHeader.test.tsx`
Expected: FAIL — `Cannot find module './ConvHeader'`.

- [ ] **Step 3: Implement `frontend/src/components/Chat/ConvHeader.tsx`**

```tsx
// frontend/src/components/Chat/ConvHeader.tsx
import { useEffect, useState } from 'react'

import type { ChatSummary } from '../../lib/api'

interface Props {
  activeProject: string
  currentChatId: string
  chats: ChatSummary[]
  onNew: () => void
  onSwitch: (chatId: string) => void
  /** Called when the history popover transitions to open — parent refreshes the list. */
  onOpen?: () => void
}

function formatChatTs(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  const sameYear = d.getFullYear() === now.getFullYear()
  return d.toLocaleDateString([], sameYear ? { month: 'short', day: '2-digit' } : { year: 'numeric', month: 'short', day: '2-digit' })
}

export default function ConvHeader({ activeProject, currentChatId, chats, onNew, onSwitch, onOpen }: Props) {
  const [open, setOpen] = useState(false)

  function toggleOpen() {
    setOpen(o => {
      const next = !o
      if (next) onOpen?.()
      return next
    })
  }

  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      const t = e.target as Element | null
      if (!t?.closest('.hist-pop') && !t?.closest('.conv-hd .hist-btn')) setOpen(false)
    }
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') setOpen(false) }
    const id = setTimeout(() => window.addEventListener('mousedown', onClick), 0)
    window.addEventListener('keydown', onKey)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Close the popover when the active project changes.
  useEffect(() => { setOpen(false) }, [activeProject])

  return (
    <>
      <div className="conv-hd">
        <button
          className={'chip hist-btn ' + (open ? 'on' : '')}
          onClick={toggleOpen}
          aria-label="Chat history"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="5.5" />
            <polyline points="8,4.5 8,8 10.5,9.5" />
          </svg>
          <span className="tip">Chat history</span>
        </button>
        <button className="chip" onClick={onNew} aria-label="New chat">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="3" x2="8" y2="13" />
            <line x1="3" y1="8" x2="13" y2="8" />
          </svg>
          <span className="tip">New chat</span>
        </button>
      </div>
      {open && (
        <div className="hist-pop" onClick={e => e.stopPropagation()}>
          <div className="h-hd">
            <span className="lab">history</span>
            <span className="scope">{activeProject}</span>
          </div>
          {chats.length === 0 ? (
            <div className="h-empty">No sessions yet.</div>
          ) : (
            <div className="h-list">
              {chats.map(c => (
                <div
                  key={c.chat_id}
                  className={'h-row ' + (c.chat_id === currentChatId ? 'active' : '')}
                  onClick={() => { onSwitch(c.chat_id); setOpen(false) }}
                >
                  <span className="kind">{c.kind}</span>
                  <span className="lbl">{c.label}</span>
                  <span className="ts">{formatChatTs(c.ts_iso)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  )
}
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && npx vitest run src/components/Chat/ConvHeader.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/ConvHeader.tsx frontend/src/components/Chat/ConvHeader.test.tsx
git commit -m "feat(chat): ConvHeader — floating history + new-chat chips with popover"
```

---

## Task 8: Frontend — mount `ConvHeader` in `ChatPanel`

**Files:**
- Modify: `frontend/src/components/Chat/ChatPanel.tsx`

`ChatPanel` only renders when not in review mode (App.tsx mounts `ReviewOverlay` instead when `activeDocId` is set), so "hidden in Review mode" is automatic — no extra gate needed. Render `ConvHeader` only when a real project is selected (`selectedId` truthy); when no project is selected the screen is the new-project EmptyHero and there's nothing to show history for.

- [ ] **Step 1: Update `frontend/src/components/Chat/ChatPanel.tsx`**

Add imports:

```typescript
import ConvHeader from './ConvHeader'
```

Subscribe to the new store slices (next to the existing `useChat` selectors):

```typescript
  const chatId = useChat(s => s.chatId)
  const chats = useChat(s => (selectedId ? s.chatsByProject[selectedId] ?? [] : []))
```

> Note: `selectedId` comes from `useProjects()` destructured at the top — make sure that selector closure is fine (it is; `selectedId` is in scope before the `useChat` call). If lint complains about reading `selectedId` inside the selector, hoist: `const chatsByProject = useChat(s => s.chatsByProject)` then `const chats = selectedId ? chatsByProject[selectedId] ?? [] : []` outside the selector.

In the returned JSX, add `<ConvHeader>` as the first child of the fragment (before `{improveJob && ...}`), guarded on `selectedId`:

```tsx
  return (
    <>
      {selectedId && (
        <ConvHeader
          activeProject={projectName}
          currentChatId={chatId}
          chats={chats}
          onNew={() => useChat.getState().newChat(selectedId)}
          onSwitch={(cid) => useChat.getState().switchChat(selectedId, cid)}
          onOpen={() => { void useChat.getState().listChats(selectedId) }}
        />
      )}
      {improveJob && (
        <ImproveBanner job={improveJob} onOpen={handleBannerOpen} />
      )}
      {/* …rest unchanged… */}
```

- [ ] **Step 2: Build + type-check**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 3: Run the full frontend unit suite (regression sweep)**

Run: `cd frontend && npx vitest run`
Expected: PASS (all suites, including the existing `chat-layout`-style component tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/ChatPanel.tsx
git commit -m "feat(chat): mount ConvHeader in ChatPanel (real project selected, hidden in review)"
```

---

## Task 9: Frontend — `FSSpine` slimming (drop meta, status dot, dir-collapse)

**Files:**
- Modify: `frontend/src/components/Spine/FSSpine.tsx`
- Modify: `frontend/src/components/Spine/spine.css`

Three changes from `pieces.jsx` lines 93-163: (1) the project rows lose the `<span className="meta">` doc-count; (2) the active project row gets a 6 px status dot colored by `STATUS_DOT[status]`; (3) the FS tree is grouped by directory with only `docs/` open by default — `reviewed/`, `versions/` collapse to a single line with their count and toggle on click; the trailing root files (`schema.json`, `README.md`) stay always-visible. This requires `buildTree` to return a grouped structure instead of a flat list.

- [ ] **Step 1: Rewrite `frontend/src/components/Spine/FSSpine.tsx`**

```tsx
// frontend/src/components/Spine/FSSpine.tsx
import { useEffect, useMemo, useState } from 'react'
import './spine.css'

import { useProjects } from '../../stores/projects'
import { useDocs } from '../../stores/docs'
import { useSchema } from '../../stores/schema'

// ── Tree node shapes ───────────────────────────────────────────────────────
type FileNode  = { kind: 'file';  name: string; stamp: string }
type GhostNode = { kind: 'ghost'; name: string }
type LeafNode  = FileNode | GhostNode
type DirGroup  = { name: string; count: number; items: LeafNode[] }
interface BuiltTree { groups: DirGroup[]; rootFiles: FileNode[] }

const STATUS_DOT: Record<string, string> = {
  live: 'var(--moss)',
  draft: 'var(--ochre)',
  empty: 'var(--ink-5)',
}

function buildTree(
  docs: import('../../types/review').DocSummary[],
  activeVersionId: string | null,
  schemaFieldCount: number,
): BuiltTree {
  // ── docs/ ──────────────────────────────────────────────────────────────
  const docsItems: LeafNode[] = []
  const first5 = docs.slice(0, 5)
  for (const doc of first5) {
    let stamp: string
    if (doc.has_reviewed) stamp = 'reviewed'
    else if (doc.has_prediction) stamp = 'pending'
    else stamp = 'new'
    docsItems.push({ kind: 'file', name: doc.filename, stamp })
  }
  const remaining = docs.length - first5.length
  if (remaining > 0) docsItems.push({ kind: 'ghost', name: `… ${remaining} more` })

  // ── reviewed/ ──────────────────────────────────────────────────────────
  const reviewedDocs = docs.filter(d => d.has_reviewed)
  const reviewedItems: LeafNode[] = []
  const first5Reviewed = reviewedDocs.slice(0, 5)
  for (const doc of first5Reviewed) reviewedItems.push({ kind: 'file', name: doc.filename, stamp: '' })
  const remainingReviewed = reviewedDocs.length - first5Reviewed.length
  if (remainingReviewed > 0) reviewedItems.push({ kind: 'ghost', name: `… ${remainingReviewed} more` })
  else if (reviewedDocs.length === 0) reviewedItems.push({ kind: 'ghost', name: '(none yet)' })

  // ── versions/ ──────────────────────────────────────────────────────────
  const versionItems: LeafNode[] = activeVersionId
    ? [{ kind: 'file', name: activeVersionId, stamp: 'frozen' }]
    : [{ kind: 'ghost', name: '(no versions yet)' }]

  // ── trailing root files ────────────────────────────────────────────────
  const rootFiles: FileNode[] = [
    { kind: 'file', name: 'schema.json', stamp: schemaFieldCount > 0 ? `${schemaFieldCount} fields` : '' },
    { kind: 'file', name: 'README.md', stamp: '' },
  ]

  return {
    groups: [
      { name: 'docs/', count: docs.length, items: docsItems },
      { name: 'reviewed/', count: reviewedDocs.length, items: reviewedItems },
      { name: 'versions/', count: activeVersionId ? 1 : 0, items: versionItems },
    ],
    rootFiles,
  }
}

export default function FSSpine() {
  const projects = useProjects(s => s.projects)
  const selectedId = useProjects(s => s.selectedId)

  const docsByProject = useDocs(s => s.byProject)
  const schemaByProject = useSchema(s => s.byProject)

  // Only docs/ open by default.
  const [openDirs, setOpenDirs] = useState<Record<string, boolean>>({ 'docs/': true })
  const toggleDir = (name: string) => setOpenDirs(s => ({ ...s, [name]: !s[name] }))

  useEffect(() => { void useProjects.getState().refresh() }, [])
  useEffect(() => {
    if (!selectedId) return
    void useDocs.getState().refresh(selectedId)
    void useSchema.getState().load(selectedId)
  }, [selectedId])

  const activeDocs = selectedId ? (docsByProject[selectedId] ?? []) : []
  const activeSchemaFields = selectedId ? (schemaByProject[selectedId] ?? []) : []
  const activeProject = projects.find(p => p.project_id === selectedId) ?? null

  const tree = useMemo<BuiltTree | null>(
    () => activeProject
      ? buildTree(activeDocs, activeProject.active_version_id ?? null, activeSchemaFields.length)
      : null,
    [activeProject, activeDocs, activeSchemaFields.length],
  )

  return (
    <div className="fs">
      <div className="fs-head">
        ~/projects <span className="small">{projects.length}</span>
      </div>

      {projects.length === 0 && (
        <div className="ghost" style={{ padding: '4px 16px' }}>no projects yet</div>
      )}
      {projects.map(p => {
        const isActive = p.project_id === selectedId
        return (
          <div
            key={p.project_id}
            className={'proj' + (isActive ? ' active' : '')}
            onClick={() => useProjects.getState().select(p.project_id)}
          >
            <span className="glyph">{isActive ? '▸' : '·'}</span>
            <span>{p.name}/</span>
            {isActive && (
              <span
                className="status-dot"
                title={p.status ?? 'empty'}
                style={{ background: STATUS_DOT[p.status ?? 'empty'] ?? 'var(--ink-5)' }}
              />
            )}
          </div>
        )
      })}

      <div
        className="proj"
        onClick={() => useProjects.getState().select(null)}
        style={{ color: 'var(--ink-4)', fontStyle: 'italic' }}
      >
        <span className="glyph">+</span>
        <span>new project…</span>
      </div>

      {activeProject && tree && (
        <>
          <hr />
          <div className="fs-head">
            {activeProject.name}/ <span className="small">ls</span>
          </div>
          <div className="tree">
            {tree.groups.map(g => {
              const open = !!openDirs[g.name]
              return (
                <div key={g.name}>
                  <div className="branch dir" onClick={() => toggleDir(g.name)}>
                    <span className="arrow">{open ? '▾' : '▸'}</span>
                    <span>{g.name}</span>
                    <span className="stamp">{g.count}</span>
                  </div>
                  {open && g.items.map((n, j) => (
                    n.kind === 'ghost'
                      ? <div key={j} className="ghost">{n.name}</div>
                      : (
                        <div key={j} className="branch file">
                          <span style={{ color: 'var(--ink-5)' }}>·</span>
                          <span>{n.name}</span>
                          {n.stamp && <span className="stamp">{n.stamp}</span>}
                        </div>
                      )
                  ))}
                </div>
              )
            })}
            {tree.rootFiles.map((n, k) => (
              <div key={'r' + k} className="branch file" style={{ paddingLeft: 18 }}>
                <span style={{ color: 'var(--ink-5)' }}>·</span>
                <span>{n.name}</span>
                {n.stamp && <span className="stamp">{n.stamp}</span>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Update `frontend/src/components/Spine/spine.css`**

Remove the now-unused `.fs .proj .meta` rule (line 9) — actually, leave it (harmless dead CSS is cheaper to leave than to risk a bad edit; if you prefer cleanliness, delete just that one line). Add the status-dot rule and make the dir branch look clickable. Append:

```css
.fs .proj .status-dot{margin-left:auto;width:6px;height:6px;border-radius:50%;flex-shrink:0}
.fs .branch.dir{cursor:default}
```

> The design's `index.html` uses `cursor:default` on `.branch.dir` (already inherited from `.fs .branch{cursor:default}`); the `pieces.jsx` reference adds an explicit `style={{cursor:'default'}}` on the dir row. Matching that — the rows aren't real links, so no `cursor:pointer`.

- [ ] **Step 3: Build + type-check**

Run: `cd frontend && npm run build`
Expected: PASS.

- [ ] **Step 4: Run the frontend unit suite**

Run: `cd frontend && npx vitest run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Spine/FSSpine.tsx frontend/src/components/Spine/spine.css
git commit -m "feat(spine): drop per-row doc-count; status dot on active project; collapse non-docs/ dirs"
```

---

## Task 10: e2e — seed a chat log + `chat-history.spec.ts`

**Files:**
- Modify: `backend/tests/e2e_seed.py`
- Create: `frontend/tests/e2e/chat-history.spec.ts`

The e2e backend runs the *real* app (`EMERGE_TEST_MODE=1` only adds `_test_stubs`, which overrides `POST /lab/chat`). `GET /lab/chats/{project_id}` hits the real route, so the seed must write a real `chats/c_*.jsonl` + meta sidecar for the spec to have a session row.

- [ ] **Step 1: Extend `backend/tests/e2e_seed.py`**

After the project is created (`pid = await create_project(...)`) and before `print(f"SEEDED ...")`, add a seeded chat:

```python
    # Seed one chat log + meta sidecar so the chat-history e2e has a session row.
    from app.chat.log import append_event, ensure_chat_meta

    seed_chat_id = "c_seed00000001"
    await append_event(workspace, pid, seed_chat_id, {"type": "user", "text": "/improve weak fields"})
    await append_event(workspace, pid, seed_chat_id, {"type": "agent_text", "text": "Seeded session for the e2e."})
    ensure_chat_meta(workspace, pid, seed_chat_id, first_user_message="/improve weak fields", has_attachments=False)
    print(f"  + seeded chat {seed_chat_id}")
```

> `c_seed00000001` matches `^c_[a-z0-9]{12}$` (`seed00000001` is exactly 12 chars: s e e d 0 0 0 0 0 0 0 1). The derived kind is `tune`, label `weak fields`.

- [ ] **Step 2: Write `frontend/tests/e2e/chat-history.spec.ts`**

```typescript
import { expect, test } from '@playwright/test'

test('chat history popover: lists the active project sessions; new-chat → empty hero; switch round-trips', async ({ page }) => {
  await page.goto('/')

  const projRow = page.locator('.proj', { hasText: 'e2e-test' })
  await expect(projRow).toBeVisible({ timeout: 10_000 })
  await projRow.click()

  // The active project row shows a status dot (this seed project is "draft").
  await expect(page.locator('.proj.active .status-dot')).toBeVisible()

  // FS tree: docs/ is open by default, reviewed/ is collapsed.
  await expect(page.locator('.branch.dir', { hasText: 'docs/' })).toBeVisible()
  // reviewed/ row exists but its children aren't rendered (collapsed).
  const reviewedDir = page.locator('.branch.dir', { hasText: 'reviewed/' })
  await expect(reviewedDir).toBeVisible()
  // Toggling docs/ hides the doc file rows.
  const docFile = page.locator('.branch.file', { hasText: 'sample.pdf' })
  await expect(docFile).toBeVisible()
  await page.locator('.branch.dir', { hasText: 'docs/' }).click()
  await expect(docFile).toHaveCount(0)
  await page.locator('.branch.dir', { hasText: 'docs/' }).click()  // re-open

  // Open the chat-history popover.
  await page.getByLabelText('Chat history').click()
  await expect(page.locator('.hist-pop')).toBeVisible()
  await expect(page.locator('.hist-pop .h-hd .lab')).toHaveText('history')
  await expect(page.locator('.hist-pop .h-hd .scope')).toHaveText('e2e-test')
  // The seeded session row.
  const seededRow = page.locator('.hist-pop .h-row', { hasText: 'weak fields' })
  await expect(seededRow).toBeVisible()
  await expect(seededRow.locator('.kind')).toHaveText('tune')

  // Switching to it loads the seeded events into the conversation.
  await seededRow.click()
  await expect(page.locator('.hist-pop')).toHaveCount(0)  // popover closed on switch
  await expect(page.getByText('Seeded session for the e2e.')).toBeVisible()

  // New chat → empty hero (no conv-inner, EmptyHero shown).
  await page.getByLabelText('New chat').click()
  await expect(page.locator('.conv-inner')).toHaveCount(0)
  // EmptyHero renders the composer; the seeded agent text is gone.
  await expect(page.getByText('Seeded session for the e2e.')).toHaveCount(0)
})
```

> If `EmptyHero` doesn't have a stable text/role to assert on, assert on `page.getByRole('textbox')` being visible plus `.conv-inner` count 0 — adjust to whatever `EmptyHero.tsx` actually renders (check it during implementation; the `chat-layout.spec.ts` uses `page.getByRole('textbox')`).

- [ ] **Step 3: Run the e2e suite**

Run: `cd frontend && npm run e2e`
Expected: PASS — the new `chat-history.spec.ts` plus the existing specs (`chat-layout`, `publish-modal`, `review-mode*`, `walking-skeleton`) all green. If `chat-layout.spec.ts` regresses because the seeded chat now makes the project show conv content on first select — it shouldn't, because that spec selects the project and *then* types `/extract`; the seeded chat is a *different* chat_id, not the active one (the active one for that project is freshly minted on first `enterProject` since there's no `emerge.activeChatId.<pid>` in a fresh browser). Confirm.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/e2e_seed.py frontend/tests/e2e/chat-history.spec.ts
git commit -m "test(e2e): seed a chat log; chat-history popover + switch + new-chat + FS-collapse spec"
```

---

## Task 11: Docs — ROADMAP row + design-decisions resolution

**Files:**
- Modify: `docs/superpowers/plans/ROADMAP.md`
- Modify: `docs/design-decisions.md`

- [ ] **Step 1: Add the M8 row to `docs/superpowers/plans/ROADMAP.md`**

In the Status table, add after the M7.2 row:

```markdown
| **M8** — chat history + new-chat + left-rail slim | `2026-05-12-m8-chat-history.md` | ✅ shipped | _(fill commit range on closeout)_ |
```

In "What each milestone delivers", add a section after M7.2:

```markdown
### M8 — chat history + new-chat + left-rail slim

**Goal:** replace the single-chat-per-project model with multiple chats per project, surfaced as a Claude-style "Chat history + New chat" chip pair at the top-right of the conversation column; ship the two adopted left-rail tweaks (drop per-row doc-count meta + status dot on the active project; collapse all FS-tree directories except `docs/`).

**Scope (see `2026-05-12-m8-chat-history.md`):**
- T1-T2: backend — `{chat_id}.meta.json` sidecar extended with `{label, kind, created_at}` (merge-aware writes; set once on the first turn); `GET /lab/chats/{project_id}` chat-list endpoint (directory scan, newest-first, legacy-log fallback). Kind taxonomy is the locked generic-verb set `init | run | tune | review | publish | ingest | chat` (slash-cmd → kind is many-to-one: `/extract` and `/eval` both → `run`; attachments on turn 1 → `ingest`).
- T3: backend — additive `status: live | draft | empty` on `GET /lab/projects`.
- T4-T5: frontend store — `chatsByProject` (server-authoritative, in-memory) + `listChats / switchChat / newChat`; localStorage key migration `emerge.chatId.<pid>` → `emerge.activeChatId.<pid>` (copy-forward, old key left for one session); chat list refreshed after every completed send.
- T6-T8: frontend UI — conv-header / history-popover CSS ported verbatim from the design handoff; `ConvHeader.tsx` (floating chips + popover, outside-click/Escape/project-switch close); mounted in `ChatPanel` (real project selected; auto-hidden in review mode since `ChatPanel` isn't rendered there).
- T9: `FSSpine` — drop the `meta` doc-count span; 6 px status dot on the active project row; FS tree grouped by directory with only `docs/` open by default (`reviewed/` / `versions/` collapse to one line + count, toggle on click); trailing root files (`schema.json`, `README.md`) stay visible.
- T10: e2e — seeded chat log + `chat-history.spec.ts` (popover lists sessions, switch round-trips, new-chat → EmptyHero, status dot, FS-collapse).

**Decisions affirmed / out of scope:** no chat deletion, rename, search, or export (not in the design — if raised, add as a cross-cutting follow-up). The chrome-level genericization (kind taxonomy, popover copy) is in scope; the sample-data-level document-type generalization (chat2.md "Issue 3") stays deferred. No `summary` field anywhere (design revision 2 dropped it) — so no new redactor path.
```

Also flip the M8 Status-table cell to `✅ shipped` only after the verification protocol below passes; during implementation it can stay `🚧 in progress`.

- [ ] **Step 2: Resolve the 2026-05-11 "Chat history survives page reload" entry in `docs/design-decisions.md`**

Find the `### 2026-05-11 — Chat history survives page reload` entry. Change its `**Status**` line to:

```markdown
- **Status**: ✅ Resolved by M8 (`docs/superpowers/plans/2026-05-12-m8-chat-history.md`) — per-project chatId persistence still applies, but the single-chat model it described is superseded by multi-chat (`emerge.chatId.<pid>` → `emerge.activeChatId.<pid>`; chats are now server-listed via `GET /lab/chats/{pid}`).
```

(Leave the rest of that entry's body intact — it's still accurate as the predecessor.)

> The 🟡 Pending entry for the new ConvHeader + chat-list shape already exists in `docs/design-decisions.md` (the "2026-05-12 — chat history" block citing `PROMPT-2026-05-12-chat-history.md` and the "2026-05-12 — UI vocabulary becomes task-type-agnostic" block). On closeout, flip those two from 🟡 Pending to ✅ Implemented and add the commit range — but that's a closeout step, not part of plan execution; note it here so it isn't forgotten.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/ROADMAP.md docs/design-decisions.md
git commit -m "docs: M8 roadmap row; resolve 2026-05-11 chat-history-reload decision (superseded by multi-chat)"
```

---

## Live verification protocol (run before declaring M8 done)

Same shape as M7.2's protocol. All of these must pass:

1. **Backend unit + integration** — `cd backend && uv run pytest -v`. Must be green. Pay attention to `test_chat_meta.py`, `test_chat_log.py` (the session-id refactor), `test_lab_chat_list.py`, `test_lab_projects.py`, `test_chat_session_continuity.py`.
2. **Frontend unit** — `cd frontend && npx vitest run`. Must be green: `chat-hydrate.test.ts` (incl. the new migration / `listChats` / `switchChat` race / `newChat` cases), `ConvHeader.test.tsx`, plus the existing suites unchanged.
3. **Frontend build** — `cd frontend && npm run build`. Must pass on the final commit (TypeScript + Vite, CSS parse).
4. **e2e** — `cd frontend && npm run e2e`. All specs green, including the new `chat-history.spec.ts`.
5. **chrome-devtools-mcp live check** against `:5173` (run `cd frontend && npm run dev` + a local backend):
   - History popover: opens on the ⏱ chip, closes on outside-click, closes on `Escape`, closes when you switch to another project in the left rail.
   - The popover header reads `history` (mono uppercase) on the left and the project name on the right — **no "N runs" count**.
   - Rows are one line: 54 px mono uppercase kind tag / serif label / tabular-nums timestamp; the current chat's row has the `--ochre-soft` background and its kind text is `--ochre-2`.
   - `+ New chat` chip → the conversation flips to EmptyHero; typing + sending creates a new chat that then appears at the top of the popover.
   - Status dot color on the active project row: seed a `live` project (a `project.json` with `active_version_id` set), a `draft` project (non-empty `schema.json`), and an `empty` project (fresh `create_project`); confirm moss / ochre / ink-5 respectively.
   - FS tree: only `docs/` is expanded on load; clicking `reviewed/` / `versions/` toggles them; `schema.json` / `README.md` stay visible at the bottom.
   - The doc-count `meta` text is gone from every project row.
6. **Screenshots** (save to `docs/screenshots/`): `2026-05-12-m8-chat-history-empty.png` (popover with `No sessions yet.`), `2026-05-12-m8-chat-history-multi.png` (popover listing several sessions, active row highlighted), `2026-05-12-m8-chat-history-switch.png` (conversation showing a switched-into older chat).

---

## Self-review notes (planner)

- **Spec coverage** vs `PROMPT-2026-05-12-chat-history.md` §4 gap checklist: 4.1 backend list endpoint → T1+T2; chat-meta storage (label/kind/created_at, no summary) → T1; kind taxonomy as generic verbs (slash-cmd → kind many-to-one) → T1 `derive_chat_kind`; delete-chat deferred (not planned, noted in ROADMAP "out of scope") ✓; no new safety/redactor surface → constraints block ✓. 4.2 store: `emerge.activeChatId.<pid>` + migration → T5; `listChats`/`switchChat`/`newChat` with race-safety reuse → T5; `enterProject` reads new key → T5; M7.1 invariants preserved (adopt logic untouched, in-flight tail preserved, `reduceEvents` pure) → T5 (only additive). 4.3 UI: `ConvHeader.tsx` props match the prompt's spec (plus `onOpen` for the fetch trigger) → T7; CSS ported verbatim → T6; `FSSpine` meta-removal + status dot + dir-collapse → T9; status field from backend → T3. 4.4 tests: backend list sorted/empty/traversal → T1+T2; frontend `listChats`/`switchChat` race/`newChat` → T5; e2e popover/switch/new-chat/status-dot/FS-collapse → T10.
- **Out-of-scope honored**: Issue 3 (sample-data document-type generalization), chat deletion/rename/search/export, dark-mode tokens — none planned.
- **Type consistency**: `ChatSummary = {chat_id, label, kind, ts_iso, n_events}` is identical across the backend `list_chats` return (T1), `api.ts` (T4), the store `chatsByProject` (T5), and `ConvHeader` props (T7). `Project.status` is `'live'|'draft'|'empty'` in both `api.ts` (T4) and the backend derivation (T3); `STATUS_DOT` keys match. Store actions `listChats`/`switchChat`/`newChat` have the same signatures in the `State` interface, the implementations, and the `ChatPanel` call sites.
- **No placeholders**: every code step has the full code; every command has its expected output.
