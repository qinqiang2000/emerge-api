import asyncio
import json
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


def read_chat_session_id(workspace: Path, project_id: str, chat_id: str) -> str | None:
    """Return the persisted SDK session id for resuming, or None."""
    meta_path = chat_meta_path(workspace, project_id, chat_id)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    sid = data.get("sdk_session_id")
    return sid if isinstance(sid, str) and sid else None


def write_chat_session_id(
    workspace: Path,
    project_id: str,
    chat_id: str,
    session_id: str | None,
) -> None:
    """Persist (or clear) the SDK session id sidecar for a chat."""
    meta_path = chat_meta_path(workspace, project_id, chat_id)
    if session_id is None:
        try:
            meta_path.unlink()
        except FileNotFoundError:
            pass
        return
    chats_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
    atomic_write_json(meta_path, {"sdk_session_id": session_id})
