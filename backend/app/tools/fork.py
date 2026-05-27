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
    docs_meta_dir,
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)
from app.workspace.pid_index import get_index


class ForkSourceNotFoundError(Exception):
    """Raised when fork_project is called with a src slug that has no project.json."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fork_project(
    workspace: Path,
    *,
    src_slug: str,
    name: str,
    include_docs: bool = False,
) -> dict[str, str]:
    """Clone-at-time fork of `src_slug` into a fresh project (new slug + pid).

    Whitelist of what gets cloned:
      - project.json   (rewritten: new pid + slug, new name, fresh publish
                        lineage — active_version_id=None, published_ids=[])
      - prompts/*.json (all named variants; _candidate/ skipped)
      - models/*.json
      - docs/*         (skipped unless include_docs=True; then hardlink+fallback)

    Everything else (chats, reviewed, predictions/_draft, experiments, versions,
    metrics, jobs, legacy schema.json/global_notes.md) is deliberately not
    cloned — see docs/superpowers/plans/2026-05-14-m9-4-fork-and-import.md
    decision matrix.

    Returns `{project_id, slug}` for the new project."""
    from app.tools.projects import _ensure_unique_slug, derive_slug
    from app.workspace.migrate import migrate_project_if_needed

    src_pj = project_json_path(workspace, src_slug)
    if not src_pj.exists():
        raise ForkSourceNotFoundError(f"src project {src_slug} not found")

    # Ensure src is on current layout before we read its prompts/models dirs.
    await migrate_project_if_needed(workspace, src_slug)

    new_pid = new_project_id()
    # Prefer a name-derived slug when caller supplies one; otherwise fall back
    # to `<src>-fork` so command-Z-ing a fork chain ("fork inv-MY twice")
    # produces deterministic-ish, debuggable folder names. Collision suffix
    # is applied either way.
    base = derive_slug(name) if name else f"{src_slug}-fork"
    if not base:
        base = f"{src_slug}-fork"
    new_slug = _ensure_unique_slug(workspace, base)
    new_dir = project_dir(workspace, new_slug)
    new_dir.mkdir(parents=True, exist_ok=False)

    # Lock is on the new slug only; src is treated as read-only / frozen
    # during a fork (concurrent writers on src would race with our reads,
    # but that's the spec's "clone-at-time" semantics).
    async with project_lock(workspace, new_slug):
        # Bootstrap only the whitelist subdirs; everything else (chats,
        # predictions, versions, reviewed, experiments, metrics, jobs) is
        # left absent so the fork starts with a clean slate.
        docs_dir(workspace, new_slug).mkdir(parents=True, exist_ok=True)
        prompts_dir(workspace, new_slug).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, new_slug).mkdir(parents=True, exist_ok=True)

        # 1. project.json
        src_blob = json.loads(src_pj.read_text(encoding="utf-8"))
        new_blob = {
            "project_id": new_pid,
            "slug": new_slug,
            "name": name,
            "project_type": src_blob.get("project_type", "extraction"),
            "created_at": _now_iso(),
            "active_prompt_id": src_blob.get("active_prompt_id"),
            "active_model_id": src_blob.get("active_model_id"),
            "active_version_id": None,  # fresh publish lineage in the fork
            "autoresearch_proposer_model": src_blob.get("autoresearch_proposer_model"),
            "published_ids": [],
        }
        atomic_write_json(project_json_path(workspace, new_slug), new_blob)

        # 2. prompts/*.json (top-level files only — _candidate/ subdir is skipped)
        src_prompts = prompts_dir(workspace, src_slug)
        if src_prompts.exists():
            for f in src_prompts.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        prompt_path(workspace, new_slug, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 3. models/*.json
        src_models = models_dir(workspace, src_slug)
        if src_models.exists():
            for f in src_models.iterdir():
                if f.is_file() and f.name.endswith(".json"):
                    atomic_write_json(
                        model_path(workspace, new_slug, f.stem),
                        json.loads(f.read_text(encoding="utf-8")),
                    )

        # 4. docs/ (optional). Two layers to clone:
        #   * top-level doc files (`docs/<filename>`) — the real bytes.
        #   * sidecar JSONs (`docs/.meta/<filename>.json`) — without these the
        #     forked project's docs would be listless / unreadable (list_docs
        #     skips files that have no sidecar). The `_render/` cache is
        #     deliberately NOT copied: it's cheap to regenerate and bulky.
        if include_docs:
            src_docs = docs_dir(workspace, src_slug)
            dst_docs = docs_dir(workspace, new_slug)
            if src_docs.exists():
                for f in src_docs.iterdir():
                    if not f.is_file():
                        continue
                    if f.name.startswith("."):
                        continue
                    target = dst_docs / f.name
                    try:
                        target.hardlink_to(f)
                    except OSError:
                        shutil.copy2(f, target)
            src_meta = docs_meta_dir(workspace, src_slug)
            if src_meta.exists():
                dst_meta = docs_meta_dir(workspace, new_slug)
                dst_meta.mkdir(parents=True, exist_ok=True)
                for f in src_meta.iterdir():
                    if not f.is_file() or not f.name.endswith(".json"):
                        continue
                    target = dst_meta / f.name
                    try:
                        target.hardlink_to(f)
                    except OSError:
                        shutil.copy2(f, target)

    get_index(workspace).register(new_pid, new_slug)
    return {"project_id": new_pid, "slug": new_slug}
