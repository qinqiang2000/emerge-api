from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.experiment import Experiment, ExperimentEval
from app.workspace.atomic import atomic_write_json
from app.workspace.ids import new_experiment_id
from app.workspace.lock import project_lock
from app.workspace.paths import (
    experiment_dir,
    experiment_meta_path,
    experiment_prediction_path,
    experiment_predictions_dir,
    experiments_dir,
    predictions_draft_dir,
    project_json_path,
)


class ExperimentNotFoundError(Exception):
    """Raised when an experiment_id has no on-disk meta.json."""


class ExperimentInUseError(Exception):
    """Raised when delete_experiment targets a promoted experiment (audit trail)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _resolve_active_prompt_id(workspace: Path, project_id: str) -> str:
    blob = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    pid_active = blob.get("active_prompt_id")
    if not pid_active:
        raise ValueError(f"project {project_id} has no active_prompt_id")
    return pid_active


async def _resolve_active_model_id(workspace: Path, project_id: str) -> str:
    blob = json.loads(project_json_path(workspace, project_id).read_text(encoding="utf-8"))
    mid_active = blob.get("active_model_id")
    if not mid_active:
        raise ValueError(f"project {project_id} has no active_model_id")
    return mid_active


async def read_experiment(
    workspace: Path, project_id: str, experiment_id: str,
) -> Experiment:
    mp = experiment_meta_path(workspace, project_id, experiment_id)
    if not mp.exists():
        raise ExperimentNotFoundError(
            f"{experiment_id} not found in project {project_id}"
        )
    return Experiment(**json.loads(mp.read_text(encoding="utf-8")))


async def create_experiment(
    workspace: Path,
    project_id: str,
    *,
    prompt_id: str | None = None,
    model_id: str | None = None,
) -> str:
    """Upsert an experiment by (prompt_id, model_id) pair.

    If an experiment with this exact (prompt, model) pair already exists (any
    status, incl. archived/promoted), returns its existing experiment_id. Else
    mints a new one with derived label `{prompt.label} × {model.label}`.

    Both axes default to the project's active. Validates that referenced prompt
    and model exist (raises PromptNotFoundError / ModelNotFoundError otherwise).
    """
    from app.tools.model import read_model
    from app.tools.prompt import read_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)

    async with project_lock(workspace, project_id):
        pid_resolved = prompt_id or await _resolve_active_prompt_id(workspace, project_id)
        mid_resolved = model_id or await _resolve_active_model_id(workspace, project_id)
        prompt = await read_prompt(workspace, project_id, pid_resolved)
        model = await read_model(workspace, project_id, mid_resolved)

        # Upsert by axes: scan for existing experiment with same (prompt, model)
        edir = experiments_dir(workspace, project_id)
        if edir.exists():
            for sub in edir.iterdir():
                if not sub.is_dir():
                    continue
                meta = sub / "meta.json"
                if not meta.exists():
                    continue
                try:
                    existing = Experiment(**json.loads(meta.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
                if existing.prompt_id == pid_resolved and existing.model_id == mid_resolved:
                    return existing.experiment_id

        # No match — mint new
        new_id = new_experiment_id()
        now = _now_iso()
        ex = Experiment(
            experiment_id=new_id,
            label=f"{prompt.label} × {model.label}",
            prompt_id=pid_resolved,
            model_id=mid_resolved,
            status="draft",
            created_at=now,
            promoted_at=None,
            notes="",
            eval=None,
        )
        experiment_dir(workspace, project_id, new_id).mkdir(parents=True, exist_ok=True)
        experiment_predictions_dir(workspace, project_id, new_id).mkdir(
            parents=True, exist_ok=True,
        )
        atomic_write_json(
            experiment_meta_path(workspace, project_id, new_id),
            ex.model_dump(mode="json"),
        )
    return new_id


async def list_experiments(
    workspace: Path,
    project_id: str,
    *,
    include_archived: bool = False,
) -> list[dict]:
    """Return summary rows for experiments in this project.

    Each row: {experiment_id, label, prompt_id, model_id, status, created_at,
               score | None}. Newest-first by created_at.
    """
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    rows: list[dict] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta_path = sub / "meta.json"
        if not meta_path.exists():
            continue
        try:
            ex = Experiment(**json.loads(meta_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        if ex.status == "archived" and not include_archived:
            continue
        rows.append({
            "experiment_id": ex.experiment_id,
            "label": ex.label,
            "prompt_id": ex.prompt_id,
            "model_id": ex.model_id,
            "status": ex.status,
            "created_at": ex.created_at,
            "score": ex.eval.score if ex.eval else None,
        })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows


async def archive_experiment(
    workspace: Path, project_id: str, experiment_id: str,
) -> None:
    """status -> 'archived'. No-op if already archived. Cannot archive a promoted
    experiment (that would lose audit trail -- raises ExperimentInUseError)."""
    async with project_lock(workspace, project_id):
        ex = await read_experiment(workspace, project_id, experiment_id)
        if ex.status == "promoted":
            raise ExperimentInUseError(
                f"cannot archive {experiment_id}: status is 'promoted' (audit trail)"
            )
        if ex.status == "archived":
            return
        updated = ex.model_copy(update={"status": "archived"})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )


async def extract_with_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
    doc_id: str,
    *,
    provider,
) -> dict:
    """Run the experiment's (prompt, model) pair on a single doc, writing the
    payload to experiments/{exp_id}/predictions/{doc_id}.json. Returns the payload.

    The caller is responsible for passing the right provider for the experiment's
    model — the MCP wrapper / HTTP route uses get_provider_for_model(
    experiment.model.provider_model_id).
    """
    from app.tools.extract import extract_one_with_schema
    from app.tools.model import read_model
    from app.tools.prompt import read_prompt

    ex = await read_experiment(workspace, project_id, experiment_id)
    prompt = await read_prompt(workspace, project_id, ex.prompt_id)
    model = await read_model(workspace, project_id, ex.model_id)

    payload = await extract_one_with_schema(
        workspace, project_id, doc_id,
        schema=prompt.schema,
        provider=provider,
        model_id=model.provider_model_id,
        params=model.params or None,
    )
    async with project_lock(workspace, project_id):
        experiment_predictions_dir(workspace, project_id, experiment_id).mkdir(
            parents=True, exist_ok=True,
        )
        atomic_write_json(
            experiment_prediction_path(workspace, project_id, experiment_id, doc_id),
            payload,
        )
    return payload


async def run_experiment_eval(
    workspace: Path,
    project_id: str,
    experiment_id: str,
    *,
    provider,
) -> dict:
    """Foreground loop: for each doc in reviewed/, ensure
    experiments/{exp_id}/predictions/{doc}.json exists (extract if missing),
    then score predictions vs reviewed (overall + per-doc). Writes the
    resulting ExperimentEval into meta.json.eval, sets status='ran'.

    Returns the eval dict (matching the persisted blob).

    Reviewed docs with no underlying doc file (rare; usually means the doc was
    deleted after review) are skipped silently — the eval coverage count
    reflects only docs that were successfully extracted.
    """
    from app.tools.extract import extract_one_with_schema
    from app.tools.model import read_model
    from app.tools.prompt import read_prompt
    from app.tools.schema import _SUPPORTED_EXTS
    from app.tools.score import score
    from app.workspace.paths import (
        doc_path,
        reviewed_dir,
    )

    ex = await read_experiment(workspace, project_id, experiment_id)
    if ex.status == "promoted":
        raise ExperimentInUseError(
            f"cannot re-eval {experiment_id}: status is 'promoted' (audit trail)"
        )
    prompt = await read_prompt(workspace, project_id, ex.prompt_id)
    model = await read_model(workspace, project_id, ex.model_id)

    rdir = reviewed_dir(workspace, project_id)
    if not rdir.exists():
        raise ValueError("project has no reviewed docs; nothing to eval against")
    reviewed_files = sorted(rdir.glob("*.json"))
    if not reviewed_files:
        raise ValueError("project has no reviewed docs; nothing to eval against")

    predictions: dict[str, list[dict]] = {}
    reviewed_payloads: dict[str, list[dict]] = {}
    per_doc: dict[str, float] = {}

    for rfile in reviewed_files:
        did = rfile.stem
        reviewed_blob = json.loads(rfile.read_text(encoding="utf-8"))
        reviewed_entities = reviewed_blob.get("entities", [])
        # ensure underlying doc exists
        if not any(
            doc_path(workspace, project_id, did, ext).exists()
            for ext in _SUPPORTED_EXTS
        ):
            continue
        # reuse cached extract if present
        ep = experiment_prediction_path(workspace, project_id, experiment_id, did)
        if ep.exists():
            payload = json.loads(ep.read_text(encoding="utf-8"))
        else:
            payload = await extract_one_with_schema(
                workspace, project_id, did,
                schema=prompt.schema,
                provider=provider,
                model_id=model.provider_model_id,
                params=model.params or None,
            )
            experiment_predictions_dir(workspace, project_id, experiment_id).mkdir(
                parents=True, exist_ok=True,
            )
            atomic_write_json(ep, payload)
        predictions[did] = payload.get("entities", [])
        reviewed_payloads[did] = reviewed_entities

    # overall score
    overall = score(prompt.schema, predictions, reviewed_payloads)
    # per-doc: re-score one doc at a time (cheap; in-memory)
    for did in predictions:
        single = score(
            prompt.schema,
            {did: predictions[did]},
            {did: reviewed_payloads[did]},
        )
        per_doc[did] = single.macro_f1

    now = _now_iso()
    eval_blob = ExperimentEval(
        ran_at=now,
        score=overall.macro_f1,
        per_field={fs.field: fs.f1 for fs in overall.per_field},
        per_doc=per_doc,
        run_id=f"r_{int(time.time())}",
        coverage=len(predictions),
    )
    async with project_lock(workspace, project_id):
        updated = ex.model_copy(update={"status": "ran", "eval": eval_blob})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )
    return eval_blob.model_dump(mode="json")


async def promote_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
) -> None:
    """Spec §3.5: set active_prompt_id + active_model_id from experiment,
    clear predictions/_draft/, copy experiment extracts into predictions/_draft/,
    mark experiment status='promoted' + promoted_at.

    All under project_lock to guarantee no concurrent freeze_version observes a
    half-state."""
    async with project_lock(workspace, project_id):
        ex = await read_experiment(workspace, project_id, experiment_id)

        # 1. switch active
        pj = project_json_path(workspace, project_id)
        project = json.loads(pj.read_text(encoding="utf-8"))
        project["active_prompt_id"] = ex.prompt_id
        project["active_model_id"] = ex.model_id
        atomic_write_json(pj, project)

        # 2. wipe + repopulate predictions/_draft/
        draft_dir = predictions_draft_dir(workspace, project_id)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        draft_dir.mkdir(parents=True, exist_ok=True)
        ex_predictions = experiment_predictions_dir(workspace, project_id, experiment_id)
        if ex_predictions.exists():
            for src in ex_predictions.glob("*.json"):
                atomic_write_json(
                    draft_dir / src.name,
                    json.loads(src.read_text(encoding="utf-8")),
                )

        # 3. mark promoted
        now = _now_iso()
        updated = ex.model_copy(update={"status": "promoted", "promoted_at": now})
        atomic_write_json(
            experiment_meta_path(workspace, project_id, experiment_id),
            updated.model_dump(mode="json"),
        )


async def delete_experiment(
    workspace: Path,
    project_id: str,
    experiment_id: str,
) -> None:
    """Physically remove experiments/{exp_id}/. Blocks deletion of a promoted
    experiment (audit trail must be preserved). Raises ExperimentNotFoundError
    if the experiment doesn't exist; ExperimentInUseError if status='promoted'.
    """
    async with project_lock(workspace, project_id):
        ex = await read_experiment(workspace, project_id, experiment_id)
        if ex.status == "promoted":
            raise ExperimentInUseError(
                f"cannot delete {experiment_id}: status is 'promoted' (audit trail)"
            )
        edir = experiment_dir(workspace, project_id, experiment_id)
        if edir.exists():
            shutil.rmtree(edir)


async def experiments_referencing_prompt(
    workspace: Path,
    project_id: str,
    prompt_id: str,
    *,
    exclude_archived: bool = True,
) -> list[str]:
    """Return experiment_ids that reference this prompt. Archived experiments
    are excluded by default; promoted ones are included (audit trail blocks
    deletion of the prompt they point at)."""
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    hits: list[str] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta = sub / "meta.json"
        if not meta.exists():
            continue
        try:
            ex = Experiment(**json.loads(meta.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        if exclude_archived and ex.status == "archived":
            continue
        if ex.prompt_id == prompt_id:
            hits.append(ex.experiment_id)
    return hits


async def experiments_referencing_model(
    workspace: Path,
    project_id: str,
    model_id: str,
    *,
    exclude_archived: bool = True,
) -> list[str]:
    """Symmetric to experiments_referencing_prompt, keyed on model_id."""
    edir = experiments_dir(workspace, project_id)
    if not edir.exists():
        return []
    hits: list[str] = []
    for sub in edir.iterdir():
        if not sub.is_dir():
            continue
        meta = sub / "meta.json"
        if not meta.exists():
            continue
        try:
            ex = Experiment(**json.loads(meta.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
        if exclude_archived and ex.status == "archived":
            continue
        if ex.model_id == model_id:
            hits.append(ex.experiment_id)
    return hits
