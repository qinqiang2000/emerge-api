"""Promote a chat-scoped attachment into the curated `docs/` sample set.

Chat attachments at `chats/<chat_id>/attachments/<filename>` are conversational
scratch — invisible to AutoResearch eval, extract predictions, and review-mode
click-to-page. They become real samples only via this explicit, user-acked
promotion path. The agent calls this **only after the user says yes** (see
the routing rules in `app/skills/emerge_extractor.md`).

This module also hosts `promote_chat_to_project`: the relocation step that
binds an unbound chat (`_chats/<cid>.*`) to a freshly minted project
(`<slug>/chats/<cid>.*`). The relocation runs inside the new project's
`project_lock` so a still-streaming SDK turn cannot race the move.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.tools.docs import upload_doc
from app.workspace.lock import project_lock
from app.workspace.paths import (
    chat_attachment_path,
    chats_dir,
    unbound_chat_attachments_dir,
    unbound_chat_log_path,
    unbound_chat_meta_path,
    unbound_chats_root,
)


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


async def relocate_unbound_chat(
    workspace: Path,
    chat_id: str,
    new_slug: str,
) -> None:
    """Move `_chats/<chat_id>.{jsonl, meta.json}` and `_chats/<chat_id>/` into
    `<new_slug>/chats/`. MUST be called inside `project_lock(workspace,
    new_slug)` so a still-streaming SDK turn cannot race the move.

    Idempotent on partial state: if any of the three source paths is missing
    the corresponding rename is skipped silently. Files at the destination
    are left untouched if the source isn't there to overwrite them. After
    the moves complete, drop a tombstone marker so any straggler
    `append_event` to the OLD `_chats/<cid>.jsonl` is silently dropped instead
    of resurrecting the unbound state."""
    src_log = unbound_chat_log_path(workspace, chat_id)
    src_meta = unbound_chat_meta_path(workspace, chat_id)
    src_att_root = unbound_chats_root(workspace) / chat_id

    dst_chats = chats_dir(workspace, new_slug)
    dst_chats.mkdir(parents=True, exist_ok=True)
    dst_log = dst_chats / f"{chat_id}.jsonl"
    dst_meta = dst_chats / f"{chat_id}.meta.json"
    dst_att_root = dst_chats / chat_id

    if src_log.exists():
        os.rename(src_log, dst_log)
    if src_meta.exists():
        os.rename(src_meta, dst_meta)
    if src_att_root.exists():
        # `os.rename` is atomic within the same filesystem; if the dst
        # already has a stub dir (it shouldn't, but be defensive), fall back
        # to moving its children one by one. SSU: callers create the project
        # fresh, so the dst is guaranteed empty in practice.
        if dst_att_root.exists():
            for child in src_att_root.iterdir():
                os.rename(child, dst_att_root / child.name)
            src_att_root.rmdir()
        else:
            os.rename(src_att_root, dst_att_root)

    # Tombstone the unbound chat so a still-running SDK turn dispatched at
    # `slug='_chats'` can't write back a trailing `agent_text` to a path that
    # no longer exists. The tombstone gate in `log.py:_unbound_chat_alive`
    # drops these writes; the warning surfaces the mis-route in server logs.
    from app.chat.log import unbound_chat_tombstone_path

    root = unbound_chats_root(workspace)
    root.mkdir(parents=True, exist_ok=True)
    unbound_chat_tombstone_path(workspace, chat_id).touch(exist_ok=True)


async def promote_chat_to_project(
    workspace: Path,
    chat_id: str,
    *,
    name: str,
    slug: str | None = None,
) -> dict[str, str]:
    """Bind an unbound chat to a fresh project.

    Steps:
      1. `create_project(name=name)` mints a project folder + pid_index entry.
      2. Inside `project_lock(workspace, new_slug)`, `os.rename` the unbound
         chat's jsonl + meta + per-chat dir under the new project's
         `chats/<chat_id>/`.
      3. Tombstone `_chats/<cid>` so trailing SDK events from a still-running
         turn don't resurrect the unbound state.

    The `slug` arg is reserved for forcing a specific folder name; today it is
    silently ignored because `create_project` derives the slug from `name`
    (matching the existing single-source-of-truth rule). The arg stays in the
    signature so future callers can override without breaking compat.

    Returns `{slug, project_id}`. Idempotent on partial state: if any of the
    three source paths under `_chats/` is missing, that rename is skipped.
    """
    # Import inside the function to avoid the `tools.projects → tools.promote`
    # cycle (projects' new `from_unbound_chat_id` path calls back into this
    # module's `relocate_unbound_chat`).
    from app.tools.projects import create_project

    _ = slug  # explicit override slot — see docstring
    proj = await create_project(workspace, name=name)
    new_slug = proj["slug"]
    pid = proj["project_id"]

    async with project_lock(workspace, new_slug):
        await relocate_unbound_chat(workspace, chat_id, new_slug)

    return {"slug": new_slug, "project_id": pid}
