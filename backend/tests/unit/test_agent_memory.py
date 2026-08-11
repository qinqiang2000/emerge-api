"""Agent-brain memory: injection, scoping, and the five-layer red line."""
from __future__ import annotations

from app.workspace.memory import (
    project_memory_dir,
    render_memory_block,
    team_memory_dir,
)


def _write_index(directory, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "MEMORY.md").write_text(body, encoding="utf-8")


def test_empty_workspace_still_teaches_how_to_write(tmp_path):
    """Turn one is exactly when the agent needs to know it HAS a notebook."""
    block = render_memory_block(tmp_path, "proj")
    assert "No notes yet." in block
    assert "Writing it down" in block


def test_both_scopes_render_with_their_paths(tmp_path):
    _write_index(project_memory_dir(tmp_path, "proj"), "- [a](a.md) — proj fact")
    _write_index(team_memory_dir(tmp_path), "- [b](b.md) — team fact")
    block = render_memory_block(tmp_path, "proj")
    assert "proj fact" in block and "team fact" in block
    assert str(project_memory_dir(tmp_path, "proj")) in block
    assert str(team_memory_dir(tmp_path)) in block


def test_other_projects_notes_do_not_leak(tmp_path):
    _write_index(project_memory_dir(tmp_path, "other"), "- [x](x.md) — other project")
    assert "other project" not in render_memory_block(tmp_path, "proj")


def test_unbound_chat_sees_team_scope_only(tmp_path):
    _write_index(team_memory_dir(tmp_path), "- [b](b.md) — team fact")
    _write_index(project_memory_dir(tmp_path, "proj"), "- [a](a.md) — proj fact")
    block = render_memory_block(tmp_path, None)
    assert "team fact" in block and "proj fact" not in block


def test_oversized_index_is_truncated_not_unbounded(tmp_path):
    """The index rides in EVERY turn's system prompt — a runaway file must not
    silently become a permanent per-message tax."""
    _write_index(project_memory_dir(tmp_path, "proj"), "- [n](n.md) — pad\n" * 4000)
    block = render_memory_block(tmp_path, "proj")
    assert "index truncated" in block
    assert len(block.encode("utf-8")) < 12 * 1024


def test_unreadable_index_degrades_quietly(tmp_path):
    d = project_memory_dir(tmp_path, "proj")
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xc3\x28")
    assert "Writing it down" in render_memory_block(tmp_path, "proj")


def test_block_states_the_five_layer_red_line(tmp_path):
    """Extraction rules must be routed to global_notes, not filed as memory —
    a rule that lands here silently stops applying once published."""
    block = render_memory_block(tmp_path, "proj")
    assert "global_notes" in block
    assert "write_schema" in block


def test_memory_is_in_the_agent_prompt_only(tmp_path):
    """Red line: the extract/labeler/proposer prompt builders must not import
    or splice memory. Guards against a future 'just add context' patch."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "app"
    offenders = [
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "render_memory_block" in p.read_text(encoding="utf-8")
        and p.name != "memory.py"
    ]
    assert offenders == ["chat/service.py"], offenders
