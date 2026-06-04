"""Per-workspace git history — the *reversibility* layer over the no-DB spine.

emerge's durability comes from `atomic_write_json` + flock (a file on disk is
always whole). This module adds the orthogonal thing durability can't: version
history — time-travel, diff, and restore over the workspace's artifact state.
Because durability is independent, commits are **best-effort / eventual**: a
missed or late commit costs a history point, never data. That is what dissolves
the "when do we commit?" problem — we can snapshot lazily without fear.

One git repo per **effective** workspace (`teams/{slug}/` in tenant mode, the
flat root in open mode). Per-team = the isolation boundary: an agent shelling
inside its team sees only its own history, and `_auth/` + `_keys.json` (true
root) stay OUT of any repo, so no secret is ever committed.

Implementation: the `git` CLI via subprocess (no new dependency — stdlib-first).
Synchronous; async callers wrap in `asyncio.to_thread`. A per-repo
`threading.Lock` serializes our own writes; git's `index.lock` covers any
cross-process race. Everything degrades gracefully when `git` is absent or a
call fails — history is a convenience, never load-bearing, so it must never
break the app.

Author identity is pinned per-invocation (`-c user.*`) so we don't depend on the
operator's global git config.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.workspace.paths import teams_root


_log = logging.getLogger(__name__)

_AUTHOR = ("emerge", "emerge@local")
_GIT_TIMEOUT = 30.0

# Derivable / transient / secret paths never enter history. SECRETS FIRST — a
# red line (CLAUDE.md): `_keys.json` (prod API keystore; `publish` writes it into
# the effective/team workspace) and `_auth/` (password + PAT hashes) MUST be
# excluded or a commit would leak them. The rest is rebuildable, owned by another
# subsystem, or noisy append-only logs (`_chats/`/`chats/`) not worth versioning.
_GITIGNORE = """\
_keys.json
_auth/
.cache/
_staging/
_trash/
_job_locks/
_chats/
chats/
.lock
.DS_Store
"""

_locks_guard = threading.Lock()
_repo_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)


def _lock_for(repo: Path) -> threading.Lock:
    key = str(repo.resolve())
    with _locks_guard:
        return _repo_locks[key]


def git_available() -> bool:
    return shutil.which("git") is not None


def _git(repo: Path, *args: str, timeout: float = _GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run `git -C repo <args>` with author identity pinned. Never raises on a
    non-zero exit — callers inspect `.returncode`. Raises only on the tool being
    missing / timing out, which callers guard with `git_available()`."""
    cmd = [
        "git",
        "-C", str(repo),
        "-c", f"user.name={_AUTHOR[0]}",
        "-c", f"user.email={_AUTHOR[1]}",
        "-c", "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def is_repo(workspace: Path) -> bool:
    return (workspace / ".git").exists()


def ensure_repo(workspace: Path) -> bool:
    """Idempotently make `workspace` a git repo with our `.gitignore` and an
    initial snapshot. Returns True when a usable repo is present afterwards,
    False when git is unavailable or init failed (the caller carries on either
    way). Safe to call on every startup."""
    if not git_available():
        return False
    if not workspace.exists():
        return False
    with _lock_for(workspace):
        if not is_repo(workspace):
            r = _git(workspace, "init", "-q")
            if r.returncode != 0:
                _log.warning("history.ensure_repo: git init failed in %s: %s", workspace, r.stderr.strip())
                return False
        # Always refresh: an existing repo from before the secret-exclusion
        # entries were added MUST pick them up, or it could leak `_keys.json`.
        gi = workspace / ".gitignore"
        if not gi.exists() or gi.read_text(encoding="utf-8") != _GITIGNORE:
            gi.write_text(_GITIGNORE, encoding="utf-8")
        _commit_locked(workspace, "init")
    return True


def commit_all(workspace: Path, message: str) -> str | None:
    """Stage everything and commit. Returns the new commit sha, or None when
    there was nothing to commit / git is unavailable / the repo isn't init'd.
    Best-effort: any failure is logged and swallowed."""
    if not git_available() or not is_repo(workspace):
        return None
    with _lock_for(workspace):
        return _commit_locked(workspace, message)


def checkpoint_all(workspace_root: Path, message: str = "checkpoint") -> int:
    """Commit any uncommitted state across the flat root AND every team
    workspace — the idle catch-all for writes that never went through a chat
    turn (UI review saves, headless route edits). Returns the number of repos
    that actually committed. Mode-agnostic: in tenant mode the root isn't a repo
    so its `commit_all` no-ops; only `teams/{slug}/` repos commit. Mirrors the
    two-layer walk in `trash.purge_all_trash`."""
    committed = 0
    if commit_all(workspace_root, message):
        committed += 1
    teams = teams_root(workspace_root)
    if teams.is_dir():
        for team_dir in teams.iterdir():
            if team_dir.is_dir() and not team_dir.name.startswith(("_", ".")):
                if commit_all(team_dir, message):
                    committed += 1
    return committed


def _commit_locked(workspace: Path, message: str) -> str | None:
    """Caller MUST hold `_lock_for(workspace)`."""
    try:
        add = _git(workspace, "add", "-A")
        if add.returncode != 0:
            _log.warning("history.commit_all: git add failed in %s: %s", workspace, add.stderr.strip())
            return None
        # --short HEAD probe avoids an extra status parse; let commit decide.
        c = _git(workspace, "commit", "-q", "--no-verify", "-m", message)
        if c.returncode != 0:
            # "nothing to commit" is the common, expected no-op — not an error.
            blob = (c.stdout + c.stderr).lower()
            if "nothing to commit" not in blob and "no changes added" not in blob:
                _log.warning("history.commit_all: git commit failed in %s: %s", workspace, (c.stderr or c.stdout).strip())
            return None
        head = _git(workspace, "rev-parse", "HEAD")
        return head.stdout.strip() or None
    except (subprocess.TimeoutExpired, OSError) as e:
        _log.warning("history.commit_all: %s in %s", e, workspace)
        return None


def log(workspace: Path, *, path: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Version timeline, newest first. `path` scopes to a sub-tree (e.g. a
    project slug). Each entry: {sha, short, ts (unix), date (iso), message}."""
    if not git_available() or not is_repo(workspace):
        return []
    args = ["log", f"-n{max(1, limit)}", "--no-color", "--pretty=format:%H%x1f%h%x1f%ct%x1f%cI%x1f%s"]
    if path:
        args += ["--", path]
    r = _git(workspace, *args)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    out: list[dict[str, Any]] = []
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        sha, short, ct, iso, msg = parts
        out.append({"sha": sha, "short": short, "ts": int(ct) if ct.isdigit() else 0, "date": iso, "message": msg})
    return out


def diff(workspace: Path, ref_a: str, ref_b: str | None = None, *, path: str | None = None) -> str:
    """Unified diff. `ref_b=None` → `ref_a` vs the working tree (what changed
    since that version). Otherwise `ref_a..ref_b`. `path` scopes to a sub-tree."""
    if not git_available() or not is_repo(workspace):
        return ""
    args = ["diff", "--no-color", ref_a]
    if ref_b:
        args.append(ref_b)
    if path:
        args += ["--", path]
    r = _git(workspace, *args)
    return r.stdout if r.returncode == 0 else ""


def restore(workspace: Path, ref: str, *, path: str | None = None) -> str | None:
    """Restore the worktree (or `path` sub-tree) to its state at `ref`, then
    commit the restoration as a NEW commit — so restore is itself forward-moving
    and reversible. Returns the new commit sha, or None on no-op/failure."""
    if not git_available() or not is_repo(workspace):
        return None
    target = path or "."
    with _lock_for(workspace):
        r = _git(workspace, "checkout", ref, "--", target)
        if r.returncode != 0:
            _log.warning("history.restore: checkout %s -- %s failed in %s: %s", ref, target, workspace, r.stderr.strip())
            return None
        scope = path or "all"
        return _commit_locked(workspace, f"restore {scope} to {ref[:12]}")
