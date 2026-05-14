from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.jobs.events import now_iso_filename_safe
from app.provider.base import Provider, TextBlock
from app.schemas.job import JobEvent, JobInfo, JobStatus
from app.schemas.score import ScoreResult
from app.schemas.schema_field import SchemaField
from app.tools.extract import extract_one_with_schema
from app.tools.score import score
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import candidate_dir, candidate_turn_path
from app.workspace.paths import reviewed_dir


PROPOSER_SYSTEM_PROMPT = """You are improving a JSON extraction schema for a document-extraction API.

Given the current schema, ground-truth reviewed examples, the latest model
predictions, the per-field score, and user inline notes, propose a revised
schema. The ONLY change you may make is rewording each field's `description`
(adding rules, sharpening format guidance, encoding edge cases the user
flagged in notes).

Hard constraints:
- DO NOT add fields.
- DO NOT remove fields.
- DO NOT rename fields.
- DO NOT retype fields.
- Keep the field order identical.
- For each field, return `name`, `type`, and `description` (and the original
  `required`/`enum`/`examples`/`children` if present), but only `description`
  may differ from the input.

Treat the user's inline `_notes` as high-priority hints - they are direct
human feedback on what's wrong. Sample errors show concrete reviewed-vs-
prediction disagreements per doc.

Output via the propose_schema tool. Include a short `rationale` explaining
which descriptions you changed and why."""


PROPOSER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["fields", "rationale"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "boolean", "date", "array<object>"],
                    },
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}


def build_proposer_user_text(
    *,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> str:
    lines: list[str] = []

    lines.append("=== current schema ===")
    for f in schema:
        lines.append(f"- {f.name} ({f.type.value}): {f.description}")

    lines.append("")
    lines.append("=== per-field score ===")
    if not per_field:
        lines.append("(no graded fields)")
    else:
        for fs in per_field:
            lines.append(
                f"- {fs['field']}: f1={fs['f1']:.2f} tp={fs['tp']} fp={fs['fp']} fn={fs['fn']}"
            )

    lines.append("")
    lines.append("=== sample errors (reviewed vs prediction) ===")
    any_err = False
    for filename, rev_entities in reviewed.items():
        rev = rev_entities[0] if rev_entities else {}
        pred_entities = predictions.get(filename, [])
        pred = pred_entities[0] if pred_entities else {}
        for f in schema:
            r = rev.get(f.name)
            p = pred.get(f.name)
            if r is not None and r != p:
                any_err = True
                lines.append(f"- {filename}.{f.name}: reviewed={r!r} predicted={p!r}")
    if not any_err:
        lines.append("(no field-level errors)")

    lines.append("")
    lines.append("=== user notes (high-priority hints) ===")
    flat: list[str] = []
    for filename, per_field_notes in notes.items():
        for fname, note in per_field_notes.items():
            flat.append(f"- {filename}.{fname}: {note}")
    if not flat:
        lines.append("(none)")
    else:
        lines.extend(flat)

    return "\n".join(lines)


class ProposerStructuralChangeError(Exception):
    """Raised when the proposer LLM tried to add/remove/rename/retype a field.
    The autoresearch loop treats this as a non-improving turn and continues."""


async def propose_schema(
    *,
    provider: Provider,
    model_id: str,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> tuple[list[SchemaField], str]:
    """One proposer LLM call. Returns (revised schema, rationale).

    Raises ProposerStructuralChangeError if the proposer attempts to add /
    remove / rename / retype any field - only `description` text may change.
    """
    user_text = build_proposer_user_text(
        schema=schema, reviewed=reviewed, predictions=predictions,
        per_field=per_field, notes=notes,
    )
    result = await provider.extract(
        model_id=model_id,
        system_prompt=PROPOSER_SYSTEM_PROMPT,
        user_content=[TextBlock(text=user_text)],
        response_schema=PROPOSER_RESPONSE_SCHEMA,
        params={"temperature": 0.2},
    )
    blob = result.raw_json
    rationale = str(blob.get("rationale", ""))
    raw_fields: list[dict[str, Any]] = list(blob.get("fields") or [])

    if len(raw_fields) != len(schema):
        raise ProposerStructuralChangeError(
            f"proposer returned {len(raw_fields)} fields; expected {len(schema)}"
        )
    proposed: list[SchemaField] = []
    for old, new in zip(schema, raw_fields):
        if new.get("name") != old.name:
            raise ProposerStructuralChangeError(
                f"proposer changed field name {old.name!r} -> {new.get('name')!r}"
            )
        if new.get("type") != old.type.value:
            raise ProposerStructuralChangeError(
                f"proposer changed type for {old.name!r} "
                f"{old.type.value!r} -> {new.get('type')!r}"
            )
        # Carry forward old metadata that the proposer doesn't touch.
        merged = old.model_dump(mode="json")
        merged["description"] = str(new.get("description", old.description))
        proposed.append(SchemaField(**merged))

    return proposed, rationale


async def score_with_schema(
    *,
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
) -> tuple[ScoreResult, dict[str, list[dict[str, Any]]]]:
    """Run extract over each reviewed doc with `schema`, then score predictions
    vs reviewed. Returns (ScoreResult, predictions_dict)."""
    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    if rdir.exists():
        for p in sorted(rdir.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])

    predictions: dict[str, list[dict[str, Any]]] = {}
    for filename in reviewed:
        out = await extract_one_with_schema(
            workspace, project_id, filename,
            schema=schema, provider=provider, model_id=model_id,
        )
        predictions[filename] = out.get("entities", [])

    result = score(schema, predictions, reviewed)
    return result, predictions


@dataclass
class AutoresearchParams:
    max_turn: int = 30
    early_stop_no_improvement: int = 5


EmitFn = Callable[[JobEvent], Awaitable[None]]


def _save_candidate_turn(
    *,
    workspace: Path,
    project_id: str,
    job_id: str,
    turn: int,
    schema: list[SchemaField],
    score_result: ScoreResult,
    predictions: dict[str, list[dict[str, Any]]],
    rationale: str,
    parent_turn: int | None,
) -> Path:
    candidate_dir(workspace, project_id, job_id).mkdir(parents=True, exist_ok=True)
    target = candidate_turn_path(workspace, project_id, job_id, turn)
    payload = {
        "turn": turn,
        "parent_turn": parent_turn,
        "schema": [f.model_dump(mode="json") for f in schema],
        "rationale": rationale,
        "macro_f1": score_result.macro_f1,
        "per_field": [fs.model_dump(mode="json") for fs in score_result.per_field],
        "predictions": predictions,
        "ts": score_result.ts,
    }
    atomic_write_json(target, payload)
    return target


async def run_autoresearch_loop(
    *,
    workspace: Path,
    project_id: str,
    job_id: str,
    initial_schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: AutoresearchParams,
    emit: EmitFn,
    cancel_event: asyncio.Event,
    pause_event: asyncio.Event,
) -> JobInfo:
    """The autoresearch loop. Returns final JobInfo with best_turn / best_macro_f1.

    Caller is responsible for persisting the JobInfo to its in-memory registry;
    per-event JSONL persistence is the caller's job too (via `emit`)."""
    info = JobInfo(
        job_id=job_id, project_id=project_id, skill="autoresearch",
        status=JobStatus.RUNNING, params={
            "max_turn": params.max_turn,
            "early_stop_no_improvement": params.early_stop_no_improvement,
        },
        created_at=now_iso_filename_safe(),
    )
    await emit(JobEvent(type="started", ts=now_iso_filename_safe(),
                        job_id=job_id, project_id=project_id))

    if cancel_event.is_set():
        await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="cancelled",
                            best_turn=None, best_macro_f1=None))
        info.status = JobStatus.CANCELLED
        return info

    baseline, baseline_predictions = await score_with_schema(
        workspace=workspace, project_id=project_id, schema=initial_schema,
        provider=provider, model_id=model_id,
    )
    _save_candidate_turn(
        workspace=workspace, project_id=project_id, job_id=job_id, turn=0,
        schema=initial_schema, score_result=baseline, predictions=baseline_predictions,
        rationale="baseline", parent_turn=None,
    )
    await emit(JobEvent(
        type="turn", ts=now_iso_filename_safe(), turn=0,
        macro_f1=baseline.macro_f1,
        per_field=[fs.model_dump(mode="json") for fs in baseline.per_field],
        saved=True,
    ))

    best_macro_f1 = baseline.macro_f1
    best_turn = 0
    no_improvement = 0
    current_schema = initial_schema

    for turn in range(1, params.max_turn + 1):
        if pause_event.is_set():
            await emit(JobEvent(type="paused", ts=now_iso_filename_safe(), turn=turn))
            while pause_event.is_set() and not cancel_event.is_set():
                await asyncio.sleep(0.05)
            if not cancel_event.is_set():
                await emit(JobEvent(type="resumed", ts=now_iso_filename_safe(), turn=turn))
        if cancel_event.is_set():
            await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="cancelled",
                                best_turn=best_turn, best_macro_f1=best_macro_f1))
            info.status = JobStatus.CANCELLED
            info.best_turn = best_turn
            info.best_macro_f1 = best_macro_f1
            return info

        reviewed_blob, notes_blob = _load_reviewed_with_notes(workspace, project_id)

        try:
            proposed, rationale = await propose_schema(
                provider=provider, model_id=model_id, schema=current_schema,
                reviewed=reviewed_blob, predictions=baseline_predictions,
                per_field=[fs.model_dump(mode="json") for fs in baseline.per_field],
                notes=notes_blob,
            )
        except ProposerStructuralChangeError as exc:
            await emit(JobEvent(type="proposer_failed", ts=now_iso_filename_safe(),
                                turn=turn, error=str(exc)))
            no_improvement += 1
            if no_improvement >= params.early_stop_no_improvement:
                await emit(JobEvent(type="ended", ts=now_iso_filename_safe(),
                                    reason="early_stop",
                                    best_turn=best_turn, best_macro_f1=best_macro_f1))
                info.status = JobStatus.DONE
                info.best_turn = best_turn
                info.best_macro_f1 = best_macro_f1
                return info
            continue

        scored, predictions = await score_with_schema(
            workspace=workspace, project_id=project_id, schema=proposed,
            provider=provider, model_id=model_id,
        )
        improved = scored.macro_f1 > best_macro_f1
        if improved:
            _save_candidate_turn(
                workspace=workspace, project_id=project_id, job_id=job_id, turn=turn,
                schema=proposed, score_result=scored, predictions=predictions,
                rationale=rationale, parent_turn=best_turn,
            )
            best_macro_f1 = scored.macro_f1
            best_turn = turn
            no_improvement = 0
        else:
            no_improvement += 1
        await emit(JobEvent(
            type="turn", ts=now_iso_filename_safe(), turn=turn,
            macro_f1=scored.macro_f1,
            per_field=[fs.model_dump(mode="json") for fs in scored.per_field],
            saved=improved, rationale=rationale,
        ))
        current_schema = proposed
        baseline = scored
        baseline_predictions = predictions

        if no_improvement >= params.early_stop_no_improvement:
            await emit(JobEvent(type="ended", ts=now_iso_filename_safe(),
                                reason="early_stop",
                                best_turn=best_turn, best_macro_f1=best_macro_f1))
            info.status = JobStatus.DONE
            info.best_turn = best_turn
            info.best_macro_f1 = best_macro_f1
            return info

    await emit(JobEvent(type="ended", ts=now_iso_filename_safe(), reason="max_turn",
                        best_turn=best_turn, best_macro_f1=best_macro_f1))
    info.status = JobStatus.DONE
    info.best_turn = best_turn
    info.best_macro_f1 = best_macro_f1
    return info


def _load_reviewed_with_notes(
    workspace: Path, project_id: str,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, str]]]:
    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    notes: dict[str, dict[str, str]] = {}
    if not rdir.exists():
        return reviewed, notes
    for p in sorted(rdir.glob("*.json")):
        blob = json.loads(p.read_text())
        reviewed[p.stem] = blob.get("entities", [])
        if blob.get("_notes"):
            notes[p.stem] = blob["_notes"]
    return reviewed, notes
