from __future__ import annotations

import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_project_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    chats_dir,
    docs_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    versions_dir,
)
from app.workspace.pid_index import get_index


# Filesystem-unsafe / control-char set we strip from derived slugs. Slashes
# would create unintended subdirs, NUL terminates C-strings, and other control
# chars round-trip badly through shells / URLs. Whitespace is normalized to a
# single `-` separately so we don't lose word boundaries in CJK + Latin mixes
# like "Q4 美国发票".
_SLUG_DROP_CHARS = re.compile(r"[\\/\x00-\x1f\x7f]")
_SLUG_WHITESPACE = re.compile(r"\s+")
_SLUG_COLLAPSE_DASH = re.compile(r"-{2,}")

# Hard cap. 64 chars matches the route-side `safe_slug` upper bound — derive
# must not produce something the validator will reject.
_SLUG_MAX_LEN = 64

# Matches the auto-mint display name `_placeholder_project_name()` writes when
# `chat_turn` mints an empty-hero project (`Chat-YYMMDD-HHMMSS`). Used by
# `rename_project` to detect a placeholder name that should track a slug
# change — versus a name the user deliberately set and wants to keep.
_PLACEHOLDER_NAME_RE = re.compile(r"^Chat-\d{6}-\d{6}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_slug(name: str) -> str:
    """Project name → fs-safe + URL-safe handle.

    Rules (in order):
      1. `.strip().lower()` for case / whitespace normalization.
      2. Replace any whitespace run with `-` so words stay separated.
      3. Drop NUL / control chars / `/` / `\\` (filesystem hostile).
      4. Collapse consecutive `-` into one, then trim leading/trailing `-`.
      5. Truncate to 64 chars (the `safe_slug` cap).
      6. Empty result falls back to `project-YYYY-MM-DD-<3 base36>` so we
         always produce a valid folder name.

    Unicode is intentionally **preserved** — CJK, accents, emoji round-trip
    unchanged. The frontend uses `encodeURIComponent` on slug path segments
    so non-ASCII handles are safe in URLs."""
    if not isinstance(name, str):
        name = ""
    # NFKC normalizes width / compat forms (full-width digits → half-width,
    # etc.) so visually-identical inputs collide deterministically.
    normalized = unicodedata.normalize("NFKC", name).strip().lower()
    # Replace whitespace runs *before* dropping bad chars so "foo / bar"
    # becomes "foo---bar" (then collapse) instead of "foobar".
    normalized = _SLUG_WHITESPACE.sub("-", normalized)
    normalized = _SLUG_DROP_CHARS.sub("", normalized)
    normalized = _SLUG_COLLAPSE_DASH.sub("-", normalized).strip("-")
    if len(normalized) > _SLUG_MAX_LEN:
        normalized = normalized[:_SLUG_MAX_LEN].rstrip("-")
    if not normalized:
        # secrets.token_hex(2) is 4 hex chars; slice to 3 to keep slug stable
        # in length and out of the random base36 namespace used by ids.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rand = secrets.token_hex(2)[:3]
        return f"project-{today}-{rand}"
    return normalized


def _ensure_unique_slug(workspace: Path, base: str) -> str:
    """Append `-2`, `-3`, … until `workspace/<slug>` is free. The base itself
    is returned untouched if no collision exists. The candidate is re-trimmed
    so the suffixed result still fits in `safe_slug`'s 64-char cap."""
    target = workspace / base
    if not target.exists():
        return base
    n = 2
    while True:
        suffix = f"-{n}"
        room = _SLUG_MAX_LEN - len(suffix)
        head = base[:room].rstrip("-") if len(base) > room else base
        candidate = f"{head}{suffix}"
        if not (workspace / candidate).exists():
            return candidate
        n += 1


def _project_status(pdir: Path, blob: dict[str, Any]) -> str:
    if blob.get("active_version_id"):
        return "live"
    # Post-M9.1: presence of non-empty schema lives in prompts/{active_prompt_id}.json
    active_pid = blob.get("active_prompt_id")
    if active_pid:
        pp = pdir / "prompts" / f"{active_pid}.json"
        if pp.exists():
            try:
                pv = json.loads(pp.read_text())
                if isinstance(pv.get("schema"), list) and len(pv["schema"]) > 0:
                    return "draft"
            except (json.JSONDecodeError, OSError):
                pass
    # Legacy fallback (pre-migration): detect by schema.json
    sp = pdir / "schema.json"
    if sp.exists():
        try:
            fields = json.loads(sp.read_text())
            if isinstance(fields, list) and len(fields) > 0:
                return "draft"
        except (json.JSONDecodeError, OSError):
            pass
    return "empty"


async def create_project(
    workspace: Path,
    *,
    name: str,
    project_type: str = "extraction",
    from_unbound_chat_id: str | None = None,
) -> dict[str, str]:
    """Create a new project. Folder name is the derived slug; an immutable
    `project_id` (pid) is also minted and persisted inside `project.json` for
    chat / jobs event-log anchoring.

    When ``from_unbound_chat_id`` is set, the named unbound chat's jsonl /
    meta / per-chat attachment dir under `_chats/` is atomically relocated
    into the new project's `chats/` (inside the project's lock) and the
    unbound slot is tombstoned. This is the agent-side entry into the
    promote flow — used from inside an unbound chat when the user says
    "make this a project".

    Returns `{project_id, slug}`. Callers that just need the folder identifier
    should use `out["slug"]` — every path helper takes the slug, not the pid.
    """
    from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
    from app.schemas.prompt_variant import PromptVariant
    from app.workspace.paths import model_path, models_dir, prompt_path, prompts_dir

    import shutil

    from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
    from app.schemas.prompt_variant import PromptVariant
    from app.workspace.paths import model_path, models_dir, prompt_path, prompts_dir

    pid = new_project_id()
    slug = _ensure_unique_slug(workspace, derive_slug(name))

    pdir = project_dir(workspace, slug)
    pdir.mkdir(parents=True, exist_ok=False)
    # Multiple atomic writes follow; if any of them fails (disk full, OOM
    # mid-serialize, etc.) the freshly-made `pdir` would be left without
    # `project.json` — an un-listable orphan that pollutes `workspace/`
    # forever (we observed both `untitled-260514-152406` and `p_unset/`
    # accumulating during dogfood). Wrap the post-mkdir setup so any failure
    # rolls the directory back. The mkdir itself is atomic per POSIX, so
    # we don't need to handle a partial-mkdir case.
    try:
        docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        predictions_draft_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        versions_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        chats_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        prompts_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, slug).mkdir(parents=True, exist_ok=True)

        settings = get_settings()
        now = _now_iso()

        pv = PromptVariant(
            prompt_id="pr_baseline",
            label="Baseline",
            schema=[],
            global_notes="",
            derived_from=None,
            created_at=now,
            updated_at=now,
        )
        atomic_write_json(prompt_path(workspace, slug, "pr_baseline"), pv.model_dump(mode="json", exclude_none=True))

        mc = ModelConfig(
            model_id="m_default",
            label="Default",
            provider=infer_provider_from_model_id(settings.default_extract_model),
            provider_model_id=settings.default_extract_model,
            params={"temperature": 0.0},
            created_at=now,
        )
        atomic_write_json(model_path(workspace, slug, "m_default"), mc.model_dump(mode="json"))

        blob = {
            "project_id": pid,
            "slug": slug,
            "name": name,
            "project_type": project_type,
            "created_at": now,
            "active_prompt_id": "pr_baseline",
            "active_model_id": "m_default",
            "active_version_id": None,
            "autoresearch_proposer_model": None,
            # `labeler_model` is intentionally null at init: leave it empty
            # and let `_resolve_labeler_model` fall through to
            # `EMERGE_DEFAULT_LABELER_MODEL` at call-time. Only `set_labeler_model`
            # (an explicit user override) ever writes a non-null value here.
            # Why: freezing the env value at create-time made `.env` updates
            # invisible to existing projects, and the agent saw a null field
            # as "labeler 还没配" even when the env had a perfectly good default.
            "labeler_model": None,
            "published_ids": [],
        }
        atomic_write_json(project_json_path(workspace, slug), blob)

        # schema.json is intentionally NOT written for new projects.
        get_index(workspace).register(pid, slug)
    except Exception:
        shutil.rmtree(pdir, ignore_errors=True)
        raise

    if from_unbound_chat_id is not None:
        # Atomic relocate of the unbound chat into the freshly minted project.
        # Hold the project lock so any in-flight `append_event(slug=_chats, ...)`
        # from a still-streaming SDK turn either lands before the rename
        # (preserved) or after the tombstone (dropped + logged).
        from app.tools.promote import relocate_unbound_chat
        from app.workspace.lock import project_lock

        async with project_lock(workspace, slug):
            await relocate_unbound_chat(workspace, from_unbound_chat_id, slug)

    return {"project_id": pid, "slug": slug}


async def rename_project(
    workspace: Path,
    slug: str,
    *,
    new_slug: str | None = None,
    name: str | None = None,
) -> dict[str, str]:
    """Rename a project. Either `new_slug` (explicit handle change) or `name`
    (derive the new slug from the new display name) must be provided. When
    only `name` is given the slug is re-derived via `derive_slug(name)` so
    name and slug stay in sync — the same single-concept rule create_project
    uses.

    Side effects:
      * `workspace/<slug>` is `os.rename`-d to `workspace/<new_slug>` (atomic
        within the same filesystem).
      * `project.json.slug` is updated; `name` is updated when supplied.
      * `pid_index` is repointed so chat-log render still resolves the pid.

    Returns `{"slug": <new_slug>}`. No-ops when the derived `new_slug` equals
    the current `slug` (the rename is idempotent for `derive_slug` round-trip
    of a slug-shaped name)."""
    from app.api.routes._safety import safe_slug
    from app.workspace.migrate import migrate_project_if_needed

    if new_slug is None and name is None:
        raise ValueError("rename_project requires `new_slug` or `name`")

    # Display-name update can also be a pure metadata edit when the caller
    # passed only `name`; we still derive the slug from it so the two stay
    # locked together. Empty / whitespace-only name is the same error the
    # previous version raised.
    cleaned_name: str | None = None
    if name is not None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("name must be non-empty")
        if len(cleaned_name) > 200:
            raise ValueError("name too long (>200 chars)")

    if new_slug is None:
        # name is guaranteed non-empty here.
        new_slug = derive_slug(cleaned_name or "")

    new_slug = _ensure_unique_slug(workspace, new_slug)
    if new_slug == slug:
        # Still apply name-only metadata update when the slug round-trips.
        if cleaned_name is not None:
            await migrate_project_if_needed(workspace, slug)
            pj = project_json_path(workspace, slug)
            if not pj.exists():
                raise FileNotFoundError(f"project not found: {slug}")
            async with project_lock(workspace, slug):
                blob = json.loads(pj.read_text())
                blob["name"] = cleaned_name
                atomic_write_json(pj, blob)
        return {"slug": slug}

    # Defensive: rename via tool from chat could feed in unsanitized input.
    # We piggy-back on the route safety helper rather than duplicate the
    # rules; it raises HTTPException(400) on bad input, which the tool
    # surfaces as an error envelope.
    safe_slug(new_slug)

    await migrate_project_if_needed(workspace, slug)
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        raise FileNotFoundError(f"project not found: {slug}")

    async with project_lock(workspace, slug):
        blob = json.loads(pj.read_text())
        pid = blob.get("project_id")
        src = project_dir(workspace, slug)
        dst = project_dir(workspace, new_slug)
        os.rename(src, dst)
        new_pj = project_json_path(workspace, new_slug)
        blob["slug"] = new_slug
        if cleaned_name is not None:
            blob["name"] = cleaned_name
        elif _PLACEHOLDER_NAME_RE.match(str(blob.get("name") or "")):
            # Slug-only rename of a still-anonymous chat-mint project: pull
            # the display name along so sidebar stops showing the auto-stamp
            # after the user has already named the slug. A name set by the
            # user (anything not matching the placeholder pattern) is left
            # alone — slug and name can legitimately diverge.
            blob["name"] = new_slug
        atomic_write_json(new_pj, blob)
        if isinstance(pid, str) and pid:
            get_index(workspace).rename(pid, slug, new_slug)

    return {"slug": new_slug}


async def list_projects(workspace: Path) -> list[dict[str, Any]]:
    from app.workspace.migrate import migrate_project_if_needed

    if not workspace.exists():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(workspace.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        pj = child / "project.json"
        if not pj.exists():
            continue
        await migrate_project_if_needed(workspace, child.name)
        blob = json.loads(pj.read_text())
        # Folder name is the source of truth for slug. project.json.slug can
        # drift when callers rename via `Bash mv` instead of `rename_project`
        # (the tool keeps both in sync; bare mv only touches the directory),
        # so we ignore whatever `blob["slug"]` says and force the folder name.
        # Without this, the lab UI shows a stale handle and the agent's next
        # rm/cp targets a path that no longer exists. Order matters: `**blob`
        # must come BEFORE the explicit overrides so they actually win.
        slug = child.name
        item: dict[str, Any] = {
            **blob,
            "slug": slug,
            "project_id": blob.get("project_id") or slug,
            "status": _project_status(child, blob),
        }
        out.append(item)
    return out


async def update_project(workspace: Path, slug: str, patch: dict[str, Any]) -> None:
    async with project_lock(workspace, slug):
        pj = project_json_path(workspace, slug)
        blob = json.loads(pj.read_text())
        blob.update(patch)
        atomic_write_json(pj, blob)


async def delete_project(workspace: Path, slug: str) -> dict[str, str]:
    """Permanently delete a whole project: `rmtree` its directory and drop the
    `pid` from the in-memory index. Raises `FileNotFoundError` if the slug does
    not exist (idempotency is the caller's job; misspellings should surface).

    Why a tool, not just `Bash rm -rf`: chat persistence lives at
    `workspace/<slug>/chats/`, and `append_event` will resurrect a half-zombie
    `chats/` if a trailing SDK message lands after the agent ran `rm -rf`. The
    log writer has a tombstone gate (`project.json` must exist), so the order
    here is precise: bury `project.json` *first*, then `rmtree` the parent.
    Even if the chat keeps streaming, no zombie folder appears.

    Returns `{deleted_slug, deleted_pid}`. After this call the slug is free for
    reuse; the frontend should redirect off the deleted project (the SSE
    `project_renamed` mechanism doesn't fit — there's no destination)."""
    import shutil

    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, slug)
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        raise FileNotFoundError(f"project not found: {slug}")

    # Snapshot pid before we unlink project.json so we can drop it from the
    # index after rmtree (the file's gone by the time we'd want to read it).
    try:
        pid = json.loads(pj.read_text()).get("project_id")
    except (OSError, json.JSONDecodeError):
        pid = None

    async with project_lock(workspace, slug):
        # Tombstone first: unlink project.json so the chat log's
        # `_project_alive` gate trips on any in-flight `append_event` from this
        # same turn before we wipe the rest of the tree. This is the critical
        # ordering — see the function docstring.
        try:
            pj.unlink()
        except FileNotFoundError:
            # Lost a race to another deleter; the rmtree below is still safe.
            pass
        shutil.rmtree(project_dir(workspace, slug), ignore_errors=True)

    if isinstance(pid, str) and pid:
        get_index(workspace).unregister(pid)

    return {"deleted_slug": slug, "deleted_pid": pid or ""}
