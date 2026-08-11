"""Agent-brain memory: injection, scoping, the five-layer red line, and the
supersede rules that keep consolidation from inventing facts."""
from __future__ import annotations

import pytest

from app.workspace.memory import (
    MemoryNoteError,
    forget_note,
    project_memory_dir,
    render_memory_block,
    team_memory_dir,
)
from app.workspace.trash import list_trash


def _write_index(directory, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "MEMORY.md").write_text(body, encoding="utf-8")


def _write_note(directory, slug: str, hook: str, body: str = "fact") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{slug}.md").write_text(body, encoding="utf-8")
    index = directory / "MEMORY.md"
    prior = index.read_text(encoding="utf-8") if index.is_file() else ""
    index.write_text(f"{prior}- [{slug}]({slug}.md) — {hook}\n", encoding="utf-8")


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


def test_block_teaches_supersede_not_merge(tmp_path):
    """The one instruction that keeps consolidation from inventing a fact.

    Merging two notes produces a third that neither original asserted, and
    nothing downstream will ever catch it. The prompt has to say so, and has to
    say that contradiction means "a fact changed", not "a duplicate".
    """
    block = render_memory_block(tmp_path, "proj")
    assert "supersede, never by" in block and "merge" in block
    assert "contradict" in block
    assert "forget_memory" in block
    # "Looks redundant" must not be sufficient grounds to delete.
    assert "positive evidence" in block


def test_index_pressure_warns_before_the_cap_not_after(tmp_path):
    """Truncation is the failure that actually loses information, so the nudge
    has to arrive while there is still room to act on it."""
    quiet = render_memory_block(tmp_path, "proj")
    assert "of its cap" not in quiet

    _write_index(project_memory_dir(tmp_path, "proj"), "- [n](n.md) — pad\n" * 250)
    loud = render_memory_block(tmp_path, "proj")
    assert "of its cap" in loud
    assert "index truncated" not in loud  # still under the cap — warned early


def test_index_pressure_is_per_scope_not_summed(tmp_path):
    """Each scope truncates against its own cap, so a full project index is
    urgent even when the team index is empty (and vice versa)."""
    _write_index(team_memory_dir(tmp_path), "- [n](n.md) — pad\n" * 250)
    _write_index(project_memory_dir(tmp_path, "proj"), "- [a](a.md) — tiny")
    assert "of its cap" in render_memory_block(tmp_path, "proj")


# ── forget_note ────────────────────────────────────────────────────────────


def test_forget_trashes_the_body_and_drops_the_index_line(tmp_path):
    """Both halves or neither: an unindexed note is invisible to every future
    turn, and a dangling line is a broken Read."""
    d = project_memory_dir(tmp_path, "proj")
    _write_note(d, "old-model", "用 gemini-flash")
    _write_note(d, "keep-me", "交付物进 _export/")

    out = forget_note(tmp_path, "proj", "old-model")
    assert out["forgotten"] and out["deindexed"]

    assert not (d / "old-model.md").exists()
    index = (d / "MEMORY.md").read_text(encoding="utf-8")
    assert "old-model.md" not in index
    assert "keep-me.md" in index  # surgical, not a rewrite


def test_forgotten_note_is_recoverable(tmp_path):
    """The supersede rules are only safe to hand an agent because a wrong call
    is undoable. `Bash rm` is what this exists to replace."""
    d = project_memory_dir(tmp_path, "proj")
    _write_note(d, "old-model", "用 gemini-flash", body="学到于 2026-06-01\n用 flash")

    forget_note(tmp_path, "proj", "old-model")
    rows = list_trash(tmp_path)
    assert len(rows) == 1
    assert rows[0]["kind"] == "memory"
    assert rows[0]["name"] == "old-model.md"
    assert rows[0]["restorable"] is True


def test_forget_says_the_index_line_is_not_replayed_on_restore(tmp_path):
    """Restoring returns the FILE; the index edit is not a move and is not
    replayed. Silently-unindexed is the failure mode this whole verb exists to
    prevent, so the gap is stated rather than left to be discovered."""
    d = project_memory_dir(tmp_path, "proj")
    _write_note(d, "a", "hook")
    assert "MEMORY.md" in forget_note(tmp_path, "proj", "a")["restore_hint"]


def test_forget_accepts_a_bare_slug_and_scopes_to_the_team_dir(tmp_path):
    _write_note(team_memory_dir(tmp_path), "cross-project", "该客户的交付节奏")
    out = forget_note(tmp_path, None, "cross-project")  # no `.md`, no slug
    assert out["note"] == "cross-project.md" and out["scope"] == "team"
    assert not (team_memory_dir(tmp_path) / "cross-project.md").exists()


def test_forget_refuses_the_index_itself(tmp_path):
    """Retiring MEMORY.md would blind the agent to every remaining note."""
    d = project_memory_dir(tmp_path, "proj")
    _write_note(d, "a", "hook")
    with pytest.raises(MemoryNoteError, match="index"):
        forget_note(tmp_path, "proj", "MEMORY.md")
    assert (d / "MEMORY.md").is_file()


def test_forget_refuses_traversal_and_unknown_notes(tmp_path):
    _write_note(project_memory_dir(tmp_path, "proj"), "a", "hook")
    with pytest.raises(MemoryNoteError):
        forget_note(tmp_path, "proj", "../../../etc/passwd")
    with pytest.raises(MemoryNoteError, match="no such note"):
        forget_note(tmp_path, "proj", "never-existed")


def test_forget_does_not_reach_another_projects_notes(tmp_path):
    _write_note(project_memory_dir(tmp_path, "other"), "secret", "别的项目")
    with pytest.raises(MemoryNoteError, match="no such note"):
        forget_note(tmp_path, "proj", "secret")
    assert (project_memory_dir(tmp_path, "other") / "secret.md").is_file()


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
