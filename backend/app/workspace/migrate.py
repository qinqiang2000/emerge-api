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
    """Idempotent lazy migration from pre-M9.1 layout to the prompts/+models/ layout.

    Trigger this at every read entry point that touches schema or model config.
    Safe under concurrent invocations: uses project_lock + double-check.

    What it does (only when prompts/ does not exist):
      1. Reads legacy schema.json -> builds prompts/pr_baseline.json
      2. Reads legacy global_notes.md (if present) -> folds into pr_baseline.global_notes
      3. Reads legacy project.extract_model + extract_params -> builds models/m_default.json
      4. Stamps project.json with active_prompt_id='pr_baseline', active_model_id='m_default'
      5. Leaves schema.json + global_notes.md on disk (cleanup deferred to later milestone)
    """
    pdir = project_dir(workspace, project_id)
    if not pdir.exists():
        return  # nothing to migrate
    if prompts_dir(workspace, project_id).exists():
        return  # fast path: already migrated

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
        atomic_write_json(prompt_path(workspace, project_id, "pr_baseline"), pv.model_dump(mode="json"))

        # Build m_default
        settings = get_settings()
        legacy_model = project.get("extract_model") or settings.default_extract_model
        legacy_params = project.get("extract_params") or {"temperature": 0.0}
        mc = ModelConfig(
            model_id="m_default",
            label=f"Default ({legacy_model})",
            provider=infer_provider_from_model_id(legacy_model),
            provider_model_id=legacy_model,
            params=legacy_params,
            created_at=project.get("created_at") or now,
        )
        atomic_write_json(model_path(workspace, project_id, "m_default"), mc.model_dump(mode="json"))

        # Stamp project.json with active pointers (preserve legacy fields for transition)
        project["active_prompt_id"] = "pr_baseline"
        project["active_model_id"] = "m_default"
        atomic_write_json(pj_path, project)

        _log.info(
            "migrate: project %s -> prompts/pr_baseline.json + models/m_default.json (provider=%s)",
            project_id, mc.provider,
        )
