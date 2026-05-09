from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.job import JobEvent


_log_lock = asyncio.Lock()


def now_iso_filename_safe() -> str:
    """ISO-8601 UTC with `:` replaced by `-` so it's safe as a filename component."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


async def append_event_jsonl(path: Path, event: JobEvent) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n"
    async with _log_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)


async def read_events(path: Path) -> list[JobEvent]:
    """Read all complete JSONL lines. Discards a final partial line silently."""
    if not path.exists():
        return []
    out: list[JobEvent] = []
    text = path.read_text(encoding="utf-8")
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        try:
            out.append(JobEvent(**json.loads(s)))
        except (json.JSONDecodeError, ValueError):
            # Partial trailing line on crash recovery — skip silently.
            continue
    return out
