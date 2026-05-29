from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.schemas.model_config import ModelConfig, infer_provider_from_model_id
from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import SchemaField
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    schema_path,
)


_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _global_notes_path(workspace: Path, project_id: str) -> Path:
    return project_dir(workspace, project_id) / "global_notes.md"


async def migrate_project_if_needed(workspace: Path, project_id: str) -> None:
    """Idempotent lazy migration to the current on-disk layout.

    Trigger this at every read entry point that touches schema, model config,
    or experiment data. Safe under concurrent invocations: uses project_lock +
    double-check. Each migration step has its own gate so callers don't need
    to know which ones apply.

    Steps:
      - M9.1: legacy schema.json -> prompts/pr_baseline.json + models/m_default.json
              (only when prompts/ does not exist)
      - M9.4: rename experiments/{eid}/extracts/ -> experiments/{eid}/predictions/
              (only when the legacy extracts/ dir is present)
      - drop-legacy-model-fields: pop `extract_model` / `extract_params` from
              project.json. Runs independently of M9.1 because projects that
              already crossed M9.1 (prompts/ exists) skip _migrate_to_m91 and
              would otherwise keep the stale legacy keys forever.
      - slug-resync: project.json.slug realigned to folder name when they
              diverge (caller used `Bash mv` instead of `rename_project`).
    """
    pdir = project_dir(workspace, project_id)
    if not pdir.exists():
        return  # nothing to migrate

    await _migrate_to_m91(workspace, project_id, pdir)
    await _migrate_experiment_predictions(workspace, project_id, pdir)
    await _drop_legacy_model_fields(workspace, project_id)
    await _backfill_m_default_label(workspace, project_id)
    await _resync_slug(workspace, project_id)


async def _drop_legacy_model_fields(workspace: Path, project_id: str) -> None:
    """Pop `extract_model` / `extract_params` from project.json — runtime
    extract reads `models/{active_model_id}.json` (M9.1+); the legacy keys
    are vestigial and confuse agents that `Read project.json`.

    Distinct from `_migrate_to_m91`: that step gates on `prompts/` not existing,
    so projects already on M9.1 never re-enter it. This step gates on the
    keys themselves being present, so it cleans up post-M9.1 blobs that
    legacy `create_project` wrote.

    Idempotent — only writes when at least one key is present.
    """
    pj = project_json_path(workspace, project_id)
    if not pj.exists():
        return
    try:
        blob = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if "extract_model" not in blob and "extract_params" not in blob:
        return
    async with project_lock(workspace, project_id):
        # Re-read under lock — another worker may have just dropped them.
        try:
            blob = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if "extract_model" not in blob and "extract_params" not in blob:
            return
        blob.pop("extract_model", None)
        blob.pop("extract_params", None)
        atomic_write_json(pj, blob)


async def _backfill_m_default_label(workspace: Path, project_id: str) -> None:
    """Rewrite legacy `m_default.label` ("Default" / "Default (model-id)") to
    just `provider_model_id`. The "Default" wording was engineering-internal
    naming that leaked into the bench rail UI; users see the same model name
    everywhere instead.

    Idempotent — only writes when the existing label is one of the legacy
    forms ("Default" or starts with "Default (").
    """
    mp = model_path(workspace, project_id, "m_default")
    if not mp.exists():
        return
    try:
        blob = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    label = blob.get("label")
    pmid = blob.get("provider_model_id")
    if not pmid:
        return
    legacy = label == "Default" or (isinstance(label, str) and label.startswith("Default ("))
    if not legacy:
        return
    async with project_lock(workspace, project_id):
        try:
            blob = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        label = blob.get("label")
        legacy = label == "Default" or (isinstance(label, str) and label.startswith("Default ("))
        if not legacy:
            return
        blob["label"] = blob.get("provider_model_id") or label
        atomic_write_json(mp, blob)


async def _resync_slug(workspace: Path, slug: str) -> None:
    """Heal stale `project.json.slug` when the folder was renamed via bare
    `Bash mv`. The folder name is the URL handle and the source of truth;
    `slug` inside the blob is just a denormalized echo that the rest of the
    code (chats, jobs, public API) doesn't read off, but agents *do* see it
    on `Read project.json` and then chase a path that no longer exists.

    Idempotent — only writes when there's an actual mismatch."""
    pj = project_json_path(workspace, slug)
    if not pj.exists():
        return
    try:
        blob = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if blob.get("slug") == slug:
        return
    async with project_lock(workspace, slug):
        # Re-read under lock — another worker may have just fixed it.
        try:
            blob = json.loads(pj.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if blob.get("slug") == slug:
            return
        blob["slug"] = slug
        atomic_write_json(pj, blob)


async def _migrate_to_m91(workspace: Path, project_id: str, pdir: Path) -> None:
    if prompts_dir(workspace, project_id).exists():
        return  # already migrated

    async with project_lock(workspace, project_id):
        # Re-check under lock
        if prompts_dir(workspace, project_id).exists():
            return

        # Read legacy state
        pj_path = project_json_path(workspace, project_id)
        if not pj_path.exists():
            _log.warning("migrate: project.json missing for %s; skipping", project_id)
            return
        project = json.loads(pj_path.read_text(encoding="utf-8"))

        sp = schema_path(workspace, project_id)
        if sp.exists():
            raw_schema = json.loads(sp.read_text(encoding="utf-8"))
        else:
            raw_schema = []

        gn_path = _global_notes_path(workspace, project_id)
        global_notes = gn_path.read_text(encoding="utf-8") if gn_path.exists() else ""

        # Build pr_baseline
        prompts_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        models_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        parsed_fields: list[SchemaField] = []
        for entry in raw_schema:
            try:
                parsed_fields.append(SchemaField(**entry))
            except Exception:
                _log.warning(
                    "migrate: dropping unparseable schema entry in %s: %r",
                    project_id, entry,
                )
                continue
        now = _now_iso()
        pv = PromptVariant(
            prompt_id="pr_baseline",
            label="Baseline",
            schema=parsed_fields,
            global_notes=global_notes,
            derived_from=None,
            created_at=project.get("created_at") or now,
            updated_at=now,
        )
        atomic_write_json(prompt_path(workspace, project_id, "pr_baseline"), pv.model_dump(mode="json", exclude_none=True))

        # Build m_default
        settings = get_settings()
        legacy_model = project.get("extract_model") or settings.default_extract_model
        legacy_params = project.get("extract_params") or {"temperature": 0.0}
        mc = ModelConfig(
            model_id="m_default",
            label=legacy_model,
            provider=infer_provider_from_model_id(legacy_model),
            provider_model_id=legacy_model,
            params=legacy_params,
            created_at=project.get("created_at") or now,
        )
        atomic_write_json(model_path(workspace, project_id, "m_default"), mc.model_dump(mode="json"))

        # Stamp project.json with active pointers AND lazily drop the legacy
        # `extract_model` / `extract_params` fields — runtime extract has long
        # since switched to `models/{active_model_id}.json` (`read_active_model`),
        # so leaving these in the blob just confuses the agent on `Read
        # project.json`. Idempotent: pop is no-op when keys are absent, so a
        # second migrate pass on an already-cleaned blob doesn't churn the
        # file.
        project["active_prompt_id"] = "pr_baseline"
        project["active_model_id"] = "m_default"
        project.pop("extract_model", None)
        project.pop("extract_params", None)
        atomic_write_json(pj_path, project)

        _log.info(
            "migrate: project %s -> prompts/pr_baseline.json + models/m_default.json (provider=%s)",
            project_id, mc.provider,
        )


async def _migrate_experiment_predictions(workspace: Path, project_id: str, pdir: Path) -> None:
    """M9.4: rename experiments/{eid}/extracts/ -> experiments/{eid}/predictions/.

    Each experiment dir is migrated independently; the lock is per-project so
    concurrent reads are safe. Skipped on projects without an experiments/ dir.
    """
    edir = pdir / "experiments"
    if not edir.exists():
        return

    candidates = [
        sub for sub in edir.iterdir()
        if sub.is_dir() and (sub / "extracts").exists() and not (sub / "predictions").exists()
    ]
    if not candidates:
        return

    async with project_lock(workspace, project_id):
        for sub in candidates:
            legacy = sub / "extracts"
            target = sub / "predictions"
            # Re-check under lock
            if not legacy.exists() or target.exists():
                continue
            legacy.rename(target)
            _log.info("migrate: %s/extracts -> %s/predictions", sub.name, sub.name)
