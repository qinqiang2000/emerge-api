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
  `required`/`enum`/`children` if present), but only `description` may differ
  from the input. Concrete value samples belong inside `description` prose
  (e.g. "Examples: ABC-123, INV-2024-001.").

Treat the user's inline `_notes` as high-priority hints - they are direct
human feedback on what's wrong. Sample errors show concrete reviewed-vs-
prediction disagreements per doc.

When your description rewording was materially driven by a user `_note`,
list the corresponding `<filename>.<field>` key in `notes_hit`. Omit fields
whose description is unchanged or whose change was driven by sample-error
analysis rather than by a user note. Hallucinated entries (notes_hit that
reference fields you did not actually change, or filenames not present in
the input) will be filtered server-side, so be conservative.

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
                        "enum": ["string", "number", "integer", "boolean", "object", "array"],
                    },
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "format": {"type": "string", "enum": ["date", "date-time", "time"]},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rationale": {"type": "string"},
        # Per Phase B plan: proposer self-declares which `<filename>.<field>`
        # user notes materially drove this turn's description rewordings.
        # Server-side `_validate_notes_hit` drops hallucinated entries before
        # they reach the candidate JSON.
        "notes_hit": {
            "type": "array",
            "items": {"type": "string"},
        },
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


def _validate_notes_hit(
    raw_hits: list[str],
    baseline_schema: list[SchemaField],
    proposed_schema: list[SchemaField],
    reviewed_dict: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], list[str]]:
    """Server-side sanity filter for proposer-declared `notes_hit`.

    The proposer LLM @ T=0.2 occasionally hallucinates — it may claim a note
    drove a change when the description text in fact didn't move (e.g. it
    reordered prose), or reference a filename that wasn't in the input. We
    drop those entries before they reach the candidate JSON so downstream
    `accept_candidate` doesn't write phantom `_notes_consumed` entries.

    Returns `(validated, filtered)`:
        - validated: hits that survived all three checks
        - filtered: hits that were dropped (preserved in candidate JSON
          under `notes_hit_filtered` for monitoring)

    Drop rules:
        (a) filename component not in `reviewed_dict`
        (b) field component not in `proposed_schema` field names
        (c) the field's description in `proposed_schema` equals its
            description in `baseline_schema` (i.e. unchanged)
    """
    baseline_desc = {f.name: f.description for f in baseline_schema}
    proposed_desc = {f.name: f.description for f in proposed_schema}
    proposed_names = set(proposed_desc)

    validated: list[str] = []
    filtered: list[str] = []
    for hit in raw_hits:
        if not isinstance(hit, str) or "." not in hit:
            filtered.append(hit if isinstance(hit, str) else str(hit))
            continue
        # Split on the LAST dot. Filenames legitimately contain dots (e.g.
        # `inv-042.pdf.buyer_name` reads as filename `inv-042.pdf` + field
        # `buyer_name`); SchemaField names are letter-led identifiers with no dot.
        filename, _, field = hit.rpartition(".")
        if not filename or not field:
            filtered.append(hit)
            continue
        if filename not in reviewed_dict:
            filtered.append(hit)
            continue
        if field not in proposed_names:
            filtered.append(hit)
            continue
        if baseline_desc.get(field) == proposed_desc.get(field):
            # Description text didn't actually change — proposer was wrong.
            filtered.append(hit)
            continue
        validated.append(hit)
    return validated, filtered


async def propose_schema(
    *,
    provider: Provider,
    model_id: str,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> tuple[list[SchemaField], str, list[str], list[str]]:
    """One proposer LLM call. Returns (revised schema, rationale,
    validated_notes_hit, filtered_notes_hit).

    The 4-tuple return arity (Phase B): the validated/filtered notes_hit
    arrays surface server-side sanity-filtering for downstream
    `accept_candidate` to write `_notes_consumed` entries against. The
    candidate JSON persists both arrays (filtered → monitoring only).

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
    raw_notes_hit: list[str] = [
        h for h in (blob.get("notes_hit") or []) if isinstance(h, str)
    ]

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

    validated_hit, filtered_hit = _validate_notes_hit(
        raw_notes_hit, schema, proposed, reviewed,
    )
    return proposed, rationale, validated_hit, filtered_hit


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
    notes_hit: list[str] | None = None,
    notes_hit_filtered: list[str] | None = None,
) -> Path:
    candidate_dir(workspace, project_id, job_id).mkdir(parents=True, exist_ok=True)
    target = candidate_turn_path(workspace, project_id, job_id, turn)
    payload: dict[str, Any] = {
        "turn": turn,
        "parent_turn": parent_turn,
        "schema": [f.model_dump(mode="json") for f in schema],
        "rationale": rationale,
        "macro_f1": score_result.macro_f1,
        "per_field": [fs.model_dump(mode="json") for fs in score_result.per_field],
        "predictions": predictions,
        "ts": score_result.ts,
    }
    # Always emit the two notes_hit arrays (empty lists OK) for downstream
    # `accept_candidate` lookup — keeps the on-disk shape uniform across the
    # baseline turn and improving turns. Baseline (turn 0) has no proposer
    # call so both lists are empty by convention.
    if notes_hit is not None:
        payload["notes_hit"] = notes_hit
    if notes_hit_filtered is not None:
        payload["notes_hit_filtered"] = notes_hit_filtered
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
        notes_hit=[], notes_hit_filtered=[],
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
            proposed, rationale, notes_hit, notes_hit_filtered = await propose_schema(
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
                notes_hit=notes_hit, notes_hit_filtered=notes_hit_filtered,
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
    """Load reviewed entities + active (unconsumed) user notes.

    Filters out any note whose field name appears as a key in the reviewed
    file's `_notes_consumed` map — those notes have already been folded
    into the schema by a prior `accept_candidate` (or manual edit) and
    re-surfacing them would have the proposer re-edit a description it
    already incorporated, then claim a fresh `notes_hit` on the same note.
    The `_notes` text itself is left intact on disk (we keep the human
    authorship for posterity / future re-consumption flows).

    Old reviewed files (pre-Phase-B, no `_notes_consumed` key) parse as
    "nothing consumed" and behave identically to the previous loop.
    """
    rdir = reviewed_dir(workspace, project_id)
    reviewed: dict[str, list[dict[str, Any]]] = {}
    notes: dict[str, dict[str, str]] = {}
    if not rdir.exists():
        return reviewed, notes
    for p in sorted(rdir.glob("*.json")):
        blob = json.loads(p.read_text())
        reviewed[p.stem] = blob.get("entities", [])
        raw_notes = blob.get("_notes") or {}
        if not raw_notes:
            continue
        consumed_map = blob.get("_notes_consumed") or {}
        consumed_keys = set(consumed_map) if isinstance(consumed_map, dict) else set()
        active = {
            fname: text for fname, text in raw_notes.items()
            if fname not in consumed_keys
        }
        if active:
            notes[p.stem] = active
    return reviewed, notes
