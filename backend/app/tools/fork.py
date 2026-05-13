from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_project_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    docs_dir,
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


class ForkSourceNotFoundError(Exception):
    """Raised when fork_project is called with a src_pid that has no project.json."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fork_project(
    workspace: Path,
    *,
    src_pid: str,
    name: str,
    include_docs: bool = False,
) -> str:
    """Clone-at-time fork of src_pid into a fresh project_id.

    Whitelist of what gets cloned:
      - project.json   (rewritten: new pid, new name, active_version_id=None)
      - prompts/*.json (all named variants; _candidate/ skipped)
      - models/*.json
      - docs/*         (skipped unless include_docs=True; then hardlink+fallback)

    Everything else (chats, reviewed, predictions/_draft, experiments, versions,
    metrics, jobs, legacy schema.json/global_notes.md) is deliberately not
    cloned — see docs/superpowers/plans/2026-05-14-m9-4-fork-and-import.md
    decision matrix.
    """
    from app.workspace.migrate import migrate_project_if_needed

    src_pj = project_json_path(workspace, src_pid)
    if not src_pj.exists():
        raise ForkSourceNotFoundError(f"src project {src_pid} not found")

    # Ensure src is on current layout before we read its prompts/models dirs.
    await migrate_project_if_needed(workspace, src_pid)

    new_pid = new_project_id()
    new_dir = project_dir(workspace, new_pid)
    new_dir.mkdir(parents=True, exist_ok=False)

    # Lock is on the new pid only; src is treated as read-only / frozen
    # during a fork (concurrent writers on src would race with our reads,
    # but that's the spec's "clone-at-time" semantics).
    async with project_lock(workspace, new_pid):
        # Bootstrap only the whitelist subdirs; everything else (chats,
        # predictions, versions, reviewed, experiments, metrics, jobs) is
        # left absent so the fork starts with a clean slate.
        docs_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)
        prompts_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, new_pid).mkdir(parents=True, exist_ok=True)

        # 1. project.json
        src_blob = json.loads(src_pj.read_text(encoding="utf-8"))
        new_blob = {
            "name": name,
            "project_type": src_blob.get("project_type", "extraction"),
            "created_at": _now_iso(),
            "active_prompt_id": src_blob.get("active_prompt_id"),
            "active_model_id": src_blob.get("active_model_id"),
            "active_version_id": None,  # fresh publish lineage in the fork
            "autoresearch_proposer_model": src_blob.get("autoresearch_proposer_model"),
            "extract_model": src_blob.get("extract_model"),
            "extract_params": src_blob.get("extract_params"),
        }
        atomic_write_json(project_json_path(workspace, new_pid), new_blob)

        # 2. prompts/*.json (top-level files only — _candidate/ subdir is skipped)
        src_prompts = prompts_dir(workspace, src_pid)
        if src_prompts.exists():
            for f in src_prompts.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        prompt_path(workspace, new_pid, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 3. models/*.json
        src_models = models_dir(workspace, src_pid)
        if src_models.exists():
            for f in src_models.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        model_path(workspace, new_pid, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 4. docs/ (optional)
        if include_docs:
            src_docs = docs_dir(workspace, src_pid)
            dst_docs = docs_dir(workspace, new_pid)
            if src_docs.exists():
                for f in src_docs.iterdir():
                    if not f.is_file():
                        continue
                    target = dst_docs / f.name
                    try:
                        target.hardlink_to(f)
                    except OSError:
                        shutil.copy2(f, target)

    return new_pid
