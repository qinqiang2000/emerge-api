"""Per-workspace git history wrapper (`workspace/history.py`).

Pins the reversibility layer: ensure_repo / commit_all / log / diff / restore,
the `.gitignore` exclusions, and graceful no-op when the repo isn't init'd.
Skipped wholesale when `git` isn't on PATH (history is a convenience, never
load-bearing).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.workspace import history

pytestmark = pytest.mark.skipif(not history.git_available(), reason="git not on PATH")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_ensure_repo_inits_with_gitignore_and_initial_commit(workspace: Path) -> None:
    assert history.ensure_repo(workspace) is True
    assert history.is_repo(workspace)
    assert (workspace / ".gitignore").exists()
    # initial snapshot exists
    assert len(history.log(workspace)) >= 1


def test_commit_all_captures_then_noops(workspace: Path) -> None:
    history.ensure_repo(workspace)
    _write(workspace / "us-invoice" / "project.json", '{"slug": "us-invoice"}')
    sha = history.commit_all(workspace, "add us-invoice")
    assert sha and len(sha) == 40
    # second commit with no change → no-op (None)
    assert history.commit_all(workspace, "noop") is None


def test_gitignore_excludes_transient_and_trash(workspace: Path) -> None:
    history.ensure_repo(workspace)
    _write(workspace / "_trash" / "x" / "f", "junk")
    _write(workspace / ".cache" / "_render" / "c", "cache")
    _write(workspace / "keep" / ".lock", "")  # project flock noise
    _write(workspace / "keep" / "project.json", "{}")
    history.commit_all(workspace, "snapshot")
    # only the real project shows up in the tree; ignored dirs/files don't
    r = history._git(workspace, "ls-files")
    tracked = r.stdout
    assert "keep/project.json" in tracked
    assert "_trash" not in tracked
    assert ".cache" not in tracked
    assert ".lock" not in tracked


def test_log_is_project_scoped_and_newest_first(workspace: Path) -> None:
    history.ensure_repo(workspace)
    _write(workspace / "alpha" / "project.json", "{}")
    history.commit_all(workspace, "alpha v1")
    _write(workspace / "beta" / "project.json", "{}")
    history.commit_all(workspace, "beta v1")

    msgs = [e["message"] for e in history.log(workspace, path="alpha")]
    assert "alpha v1" in msgs
    assert "beta v1" not in msgs  # scoping works
    # newest-first across the whole workspace
    all_msgs = [e["message"] for e in history.log(workspace)]
    assert all_msgs.index("beta v1") < all_msgs.index("alpha v1")


def test_diff_between_versions(workspace: Path) -> None:
    history.ensure_repo(workspace)
    notes = workspace / "p" / "global_notes.md"
    _write(notes, "old guidance\n")
    v1 = history.commit_all(workspace, "v1")
    _write(notes, "new guidance\n")
    v2 = history.commit_all(workspace, "v2")
    assert v1 and v2

    d = history.diff(workspace, v1, v2)
    assert "-old guidance" in d
    assert "+new guidance" in d


def test_restore_recovers_and_is_a_new_commit(workspace: Path) -> None:
    history.ensure_repo(workspace)
    schema = workspace / "p" / "schema.json"
    _write(schema, '{"v": 1}')
    v1 = history.commit_all(workspace, "v1")
    _write(schema, '{"v": 2}')
    history.commit_all(workspace, "v2")
    before = len(history.log(workspace))

    new_sha = history.restore(workspace, v1, path="p")
    assert new_sha is not None
    assert schema.read_text() == '{"v": 1}'  # content recovered
    assert len(history.log(workspace)) == before + 1  # restore is forward-moving


def test_ops_noop_on_non_repo(workspace: Path) -> None:
    # workspace exists but was never init'd → every read is an empty no-op
    assert history.commit_all(workspace, "x") is None
    assert history.log(workspace) == []
    assert history.diff(workspace, "HEAD") == ""
    assert history.restore(workspace, "HEAD") is None


def test_gitignore_excludes_secrets(workspace: Path) -> None:
    """RED LINE: prod keystore + auth hashes must never be committed. `publish`
    can write `_keys.json` into a team workspace, so the repo MUST ignore it."""
    history.ensure_repo(workspace)
    (workspace / "_keys.json").write_text('{"ek_secret": "x"}')
    (workspace / "_auth").mkdir()
    (workspace / "_auth" / "pats.json").write_text("[]")
    _write(workspace / "real" / "project.json", "{}")
    history.commit_all(workspace, "snapshot")
    tracked = history._git(workspace, "ls-files").stdout
    assert "real/project.json" in tracked
    assert "_keys.json" not in tracked
    assert "_auth" not in tracked


def test_gitignore_refreshes_on_existing_repo(workspace: Path) -> None:
    """An older repo with a stale .gitignore must pick up the secret exclusions
    on the next ensure_repo (idempotent refresh)."""
    history.ensure_repo(workspace)
    (workspace / ".gitignore").write_text("# stale, missing _keys.json\n")
    history.ensure_repo(workspace)  # should rewrite
    assert "_keys.json" in (workspace / ".gitignore").read_text()


def test_checkpoint_all_commits_dirty_team_repos(workspace: Path) -> None:
    """The idle catch-all commits out-of-turn edits across team workspaces."""
    team = workspace / "teams" / "honor"
    team.mkdir(parents=True)
    history.ensure_repo(team)
    _write(team / "p" / "schema.json", '{"v": 1}')  # an out-of-turn edit
    n = history.checkpoint_all(workspace)
    assert n == 1
    assert any("checkpoint" in e["message"] for e in history.log(team))
    # second pass with nothing dirty → no new commit
    assert history.checkpoint_all(workspace) == 0
