"""Scrub plaintext API keys from existing chat jsonls.

Usage:
    cd backend && uv run python -m app.scripts.scrub_chat_logs
    cd backend && uv run python -m app.scripts.scrub_chat_logs --dry-run

Walks every workspace/p_*/chats/c_*.jsonl, replays each event through
EventRedactor, and rewrites the file in place when any line changed. Idempotent:
running it twice does nothing on the second pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.chat.redactor import EventRedactor
from app.config import get_settings


def scrub_chat_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Return (lines_scrubbed, total_lines)."""
    redactor = EventRedactor()
    out: list[str] = []
    scrubbed = 0
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    for line in raw_lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            out.append(line)
            continue
        etype = ev.pop("type", None)
        if etype is None:
            out.append(line)
            continue
        redactor.observe(etype, ev)
        new = redactor.scrub_for_persist(etype, ev)
        if new != ev:
            scrubbed += 1
        out.append(json.dumps({"type": etype, **new}, ensure_ascii=False))
    if not dry_run and scrubbed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return scrubbed, len(raw_lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    workspace = get_settings().workspace_root
    total_files = total_scrubbed = total_lines = 0
    for chat_file in workspace.glob("p_*/chats/c_*.jsonl"):
        s, n = scrub_chat_file(chat_file, args.dry_run)
        if s:
            print(
                f"{'[dry-run] ' if args.dry_run else ''}"
                f"scrubbed {s}/{n} lines  {chat_file}"
            )
        total_files += 1
        total_scrubbed += s
        total_lines += n
    print(
        f"\nDone: {total_scrubbed} entries scrubbed across {total_files} chat "
        f"files ({total_lines} lines total)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
