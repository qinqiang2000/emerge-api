import asyncio
import json
from pathlib import Path
from typing import Any

from app.workspace.paths import chats_dir


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
