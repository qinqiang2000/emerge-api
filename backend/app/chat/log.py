import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_json
from app.workspace.paths import chat_meta_path, chats_dir


_log_lock = asyncio.Lock()


async def append_event(
    workspace: Path,
    project_id: str,
    chat_id: str,
    event: dict[str, Any],
) -> None:
    cdir = chats_dir(workspace, project_id)
    cdir.mkdir(parents=True, exist_ok=True)
    log_path = cdir / f"{chat_id}.jsonl"
    line = json.dumps(event, ensure_ascii=False) + "\n"
    async with _log_lock:
        # Append-only, JSONL, no atomic rename (a partial trailing line is recoverable).
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)


def rewind_to_user(
    workspace: Path,
    project_id: str,
    chat_id: str,
    *,
    target_user_index: int | None = None,
) -> int:
    """Truncate events.jsonl at the start of a ``{"type":"user"}`` line and
    clear the SDK session-id sidecar so the next turn starts a fresh session.

    ``target_user_index`` is a 0-indexed ordinal counting only user lines from
    the file start (so 0 = first user line, 1 = second, ...). When ``None``,
    truncates at the *last* user line — the default for composer-after-Stop
    auto-cleanup. Out-of-range index → no-op truncate (sidecar still cleared).

    Returns the new file size in bytes. Idempotent: missing file, empty file,
    or no matching user line → 0 / current size, no-op truncate (sidecar still
    cleared so the call is safe to retry). Pairs with the UI's retry / edit
    flow on any user bubble — see ``useChat.rewindAndSend``.
    """
    log_path = chats_dir(workspace, project_id) / f"{chat_id}.jsonl"
    new_size = 0
    if log_path.exists():
        try:
            raw = log_path.read_bytes()
        except OSError:
            raw = b""
        # Walk the file collecting `(line_start_offset)` for every user line.
        user_offsets: list[int] = []
        line_start = 0
        for idx, byte in enumerate(raw):
            if byte == 0x0A:  # '\n'
                stripped = raw[line_start:idx].strip()
                if stripped:
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        obj = None
                    if isinstance(obj, dict) and obj.get("type") == "user":
                        user_offsets.append(line_start)
                line_start = idx + 1
        # Trailing line without a final newline (partial write).
        if line_start < len(raw):
            stripped = raw[line_start:].strip()
            if stripped:
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict) and obj.get("type") == "user":
                    user_offsets.append(line_start)

        cut_at: int | None = None
        if user_offsets:
            if target_user_index is None:
                cut_at = user_offsets[-1]
            elif 0 <= target_user_index < len(user_offsets):
                cut_at = user_offsets[target_user_index]
        if cut_at is not None:
            try:
                with log_path.open("r+b") as f:
                    f.truncate(cut_at)
                new_size = cut_at
            except OSError:
                new_size = len(raw)
        else:
            new_size = len(raw)
    write_chat_session_id(workspace, project_id, chat_id, None)
    return new_size


# Back-compat alias for tests / callers using the old name.
rewind_to_last_user = rewind_to_user


def read_chat_events(workspace: Path, project_id: str, chat_id: str) -> list[dict[str, Any]]:
    """Read back the JSONL chat log for UI replay. Returns [] if no/unreadable log file."""
    log_path = chats_dir(workspace, project_id) / f"{chat_id}.jsonl"
    if not log_path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # A partial trailing line (or any junk) is skipped — recoverable.
                    continue
    except OSError:
        # Corrupt/locked log degrades to empty history rather than 500ing the GET.
        return []
    return out


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
