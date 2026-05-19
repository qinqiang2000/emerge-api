"""Path helpers for the unbound-chat storage layout."""
from pathlib import Path

from app.workspace.paths import (
    unbound_chat_attachment_path,
    unbound_chat_attachments_dir,
    unbound_chat_log_path,
    unbound_chat_meta_path,
    unbound_chats_root,
)


def test_unbound_chats_root_is_underscored(workspace: Path) -> None:
    """`_chats` must lead with an underscore so `list_projects` (which skips
    underscore-prefixed children) never surfaces it as a project."""
    root = unbound_chats_root(workspace)
    assert root == workspace / "_chats"
    assert root.name.startswith("_")


def test_unbound_chat_log_path_layout(workspace: Path) -> None:
    p = unbound_chat_log_path(workspace, "c_abc123def456")
    assert p == workspace / "_chats" / "c_abc123def456.jsonl"


def test_unbound_chat_meta_path_layout(workspace: Path) -> None:
    p = unbound_chat_meta_path(workspace, "c_abc123def456")
    assert p == workspace / "_chats" / "c_abc123def456.meta.json"


def test_unbound_chat_attachments_dir_layout(workspace: Path) -> None:
    d = unbound_chat_attachments_dir(workspace, "c_abc123def456")
    assert d == workspace / "_chats" / "c_abc123def456" / "attachments"


def test_unbound_chat_attachment_path_layout(workspace: Path) -> None:
    p = unbound_chat_attachment_path(workspace, "c_abc123def456", "scan.pdf")
    assert p == (
        workspace / "_chats" / "c_abc123def456" / "attachments" / "scan.pdf"
    )


def test_unbound_paths_dont_collide_with_staging(workspace: Path) -> None:
    """`_chats/` and `_staging/` are siblings, both system dirs. A future
    refactor that confused them would silently delete user attachments — pin
    the invariant explicitly."""
    assert unbound_chats_root(workspace) != workspace / "_staging"
