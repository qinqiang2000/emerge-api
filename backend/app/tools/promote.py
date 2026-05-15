"""Promote a chat-scoped attachment into the curated `docs/` sample set.

Chat attachments at `chats/<chat_id>/attachments/<filename>` are conversational
scratch — invisible to AutoResearch eval, extract predictions, and review-mode
click-to-page. They become real samples only via this explicit, user-acked
promotion path. The agent calls this **only after the user says yes** (see
the routing rules in `app/skills/emerge_extractor.md`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.docs import upload_doc
from app.workspace.paths import chat_attachment_path


async def promote_attachment_to_docs(
    workspace: Path,
    slug: str,
    chat_id: str,
    filename: str,
) -> dict[str, Any]:
    """Move a chat attachment into `docs/` via the regular `upload_doc`
    pipeline (sidecar + sha256 + page_count + dedupe inside `project_lock`).

    Deletes the chat-attachment source on success. Returns `{final_name}` —
    the post-dedupe on-disk handle (may differ from the chat filename if
    `docs/` already had a collision)."""
    src = chat_attachment_path(workspace, slug, chat_id, filename)
    if not src.exists() or not src.is_file():
        raise FileNotFoundError(
            f"chat attachment not found: {slug}/{chat_id}/{filename}",
        )
    data = src.read_bytes()
    meta = await upload_doc(workspace, slug, data, filename)
    try:
        src.unlink()
    except FileNotFoundError:
        pass
    return {"final_name": meta["filename"]}
