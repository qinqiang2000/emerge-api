"""In-memory `project_id` ↔ `slug` reverse index.

After slug-transparency (see `docs/superpowers/plans/...-pslug.md`), the folder
name *is* the slug — agent tools and lab routes use slug everywhere. But chat /
jobs jsonl events still carry the immutable `p_xxx` event anchor because event
streams must never rewrite history when a user renames a project.

When we render those events we need `p_xxx → current slug`. That's the *only*
use case for this index. **Public `/v1/extract` does not consult it** — it
resolves `published_id` against `_published/{pub}.json`, which is self-
contained.

Concurrency: single-worker FastAPI, so a plain dict guarded by the GIL is
sufficient. We add a workspace-dir-mtime check on miss to catch the case where
another process (e.g. test harness) wrote a project folder behind our back.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock


class PidIndex:
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace
        self._pid_to_slug: dict[str, str] = {}
        self._slug_to_pid: dict[str, str] = {}
        self._lock = Lock()
        # Track the workspace root mtime so we can cheaply detect folders that
        # appeared/disappeared behind our back and trigger a rescan on miss.
        self._scanned_mtime: float = -1.0
        self._scan()

    # ----- public API ------------------------------------------------------

    def resolve_pid(self, pid: str) -> str | None:
        """pid → slug. Returns None if the pid is unknown after a rescan."""
        slug = self._pid_to_slug.get(pid)
        if slug is not None:
            return slug
        if self._workspace_mtime_changed():
            self._scan()
            return self._pid_to_slug.get(pid)
        return None

    def resolve_slug(self, slug: str) -> str | None:
        """slug → pid. Symmetric helper for tests and any future audit path."""
        pid = self._slug_to_pid.get(slug)
        if pid is not None:
            return pid
        if self._workspace_mtime_changed():
            self._scan()
            return self._slug_to_pid.get(slug)
        return None

    def register(self, pid: str, slug: str) -> None:
        with self._lock:
            # Drop any stale rows that would conflict with the new pair.
            old_slug = self._pid_to_slug.pop(pid, None)
            if old_slug is not None and self._slug_to_pid.get(old_slug) == pid:
                self._slug_to_pid.pop(old_slug, None)
            old_pid = self._slug_to_pid.pop(slug, None)
            if old_pid is not None and self._pid_to_slug.get(old_pid) == slug:
                self._pid_to_slug.pop(old_pid, None)
            self._pid_to_slug[pid] = slug
            self._slug_to_pid[slug] = pid

    def unregister(self, pid: str) -> None:
        with self._lock:
            slug = self._pid_to_slug.pop(pid, None)
            if slug is not None and self._slug_to_pid.get(slug) == pid:
                self._slug_to_pid.pop(slug, None)

    def rename(self, pid: str, old_slug: str, new_slug: str) -> None:
        with self._lock:
            if self._slug_to_pid.get(old_slug) == pid:
                self._slug_to_pid.pop(old_slug, None)
            self._pid_to_slug[pid] = new_slug
            self._slug_to_pid[new_slug] = pid

    # ----- internals -------------------------------------------------------

    def _workspace_mtime_changed(self) -> bool:
        try:
            return self._workspace.stat().st_mtime != self._scanned_mtime
        except FileNotFoundError:
            return False

    def _scan(self) -> None:
        with self._lock:
            self._pid_to_slug.clear()
            self._slug_to_pid.clear()
            try:
                self._scanned_mtime = self._workspace.stat().st_mtime
            except FileNotFoundError:
                self._scanned_mtime = -1.0
                return
            for child in self._workspace.iterdir():
                if not child.is_dir():
                    continue
                if child.name.startswith("_") or child.name.startswith("."):
                    # Reserved (e.g. `_published`, `_job_locks`, `_keys.json`).
                    continue
                pj = child / "project.json"
                if not pj.is_file():
                    continue
                try:
                    data = json.loads(pj.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                pid = data.get("project_id")
                if not isinstance(pid, str) or not pid:
                    continue
                slug = child.name
                self._pid_to_slug[pid] = slug
                self._slug_to_pid[slug] = pid


_index_by_workspace: dict[Path, PidIndex] = {}
_factory_lock = Lock()


def get_index(workspace: Path) -> PidIndex:
    """Return a process-wide singleton PidIndex per workspace root.

    Tests pass `tmp_path` workspaces, so we key on the resolved path. Within a
    process, callsites should treat the returned object as long-lived: they may
    `register` after create_project, `rename` after rename_project, etc."""
    key = workspace.resolve() if workspace.exists() else workspace
    with _factory_lock:
        idx = _index_by_workspace.get(key)
        if idx is None:
            idx = PidIndex(workspace)
            _index_by_workspace[key] = idx
        return idx
