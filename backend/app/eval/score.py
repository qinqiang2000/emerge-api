from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.eval.judge import judge_batch
from app.eval.normalize import normalize_equivalent
from app.eval.pivot import cells_to_csv
from app.eval.presence import (
    DEFAULT_PROJECT_POLICY,
    AbsentPolicy,
    is_absent,
    resolve_policy,
)
from app.eval.types import CellVerdict
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import FieldScore, ScoreResultSummary
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
    predictions_draft_dir,
    project_json_path,
    reviewed_dir,
)


def _validate_project_id(project_id: str) -> None:
    if (
        not isinstance(project_id, str)
        or not project_id
        or "/" in project_id
        or "\\" in project_id
        or project_id in (".", "..")
        or "\x00" in project_id
    ):
        raise ValueError("invalid project_id")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _cell_absent_both(filename: str, entity_idx: int, field_name: str) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field_name,
        status="absent_both", verdict_source="presence",
    )


def _cell_missing(filename: str, entity_idx: int, field: SchemaField, truth_v: Any) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field.name,
        status="missing", truth=_str_or_none(truth_v),
        verdict_source="presence",
    )


def _cell_spurious(filename: str, entity_idx: int, field: SchemaField, pred_v: Any) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field.name,
        status="spurious", pred=_str_or_none(pred_v),
        verdict_source="presence",
    )


def _aggregate(
    cells: list[CellVerdict],
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
) -> tuple[list[FieldScore], float, float, float, float, int]:
    """M12.x — accuracy-first aggregation.

    Per-field `accuracy = (correct + absent_both) / total`. The model nailing
    "this field has no value" (absent_both) is a correct prediction, not a
    non-event. F1/precision/recall are no longer computed in the hot path —
    emitted as `None` so legacy summaries still validate via the demoted
    optional schema, but new writes don't carry stale F1 numbers.

    `not_applicable=True` when `total==0` (defensive — schema has the field
    but no entity ever exposed it). Macro accuracy excludes these.

    M12.x.c — three doc-level numbers:
      * `doc_accuracy` (smooth): mean over graded docs of
        (correct + absent_both) / total_cells_in_doc. Replaces the brittle
        all-or-nothing strict number as the new headline.
      * `doc_accuracy_without_array`: same as smooth, but drops cells where
        the schema field has `type == ARRAY`. Array fields (e.g. `items`)
        are the brittleness magnet; this sibling gives a clean signal on
        header fields. Falls back to `doc_accuracy` when schema has no
        array fields.
      * `doc_accuracy_strict` (legacy): the old "all cells correct/absent_both"
        definition, kept for "is this doc 100% perfect?" signal.
    """
    counts: dict[str, dict[str, int]] = {
        f.name: {"correct": 0, "total": 0, "absent_both": 0}
        for f in schema
    }
    for c in cells:
        if c.field not in counts:
            continue
        d = counts[c.field]
        d["total"] += 1
        if c.status == "correct":
            d["correct"] += 1
        elif c.status == "absent_both":
            # The hard rule: model agreed there's nothing here, ground truth
            # agreed there's nothing here — that's a correct prediction.
            d["correct"] += 1
            d["absent_both"] += 1

    per_field: list[FieldScore] = []
    for f in schema:
        d = counts[f.name]
        not_applicable = d["total"] == 0
        accuracy = (d["correct"] / d["total"]) if d["total"] > 0 else 0.0
        per_field.append(FieldScore(
            field=f.name,
            correct=d["correct"],
            total=d["total"],
            n_absent_both=d["absent_both"],
            not_applicable=not_applicable,
            accuracy=accuracy,
            # F1 family deliberately None on new writes.
            tp=None, fp=None, fn=None, support=None,
            precision=None, recall=None, f1=None,
        ))

    applicable = [p for p in per_field if not p.not_applicable]
    field_accuracy_macro = (
        sum(p.accuracy or 0.0 for p in applicable) / len(applicable)
        if applicable else 0.0
    )

    docs_seen: dict[str, list[CellVerdict]] = {}
    for c in cells:
        docs_seen.setdefault(c.filename, []).append(c)
    n_reviewed_graded = sum(1 for fn in reviewed if fn in docs_seen)

    def _ok(c: CellVerdict) -> bool:
        return c.status in ("correct", "absent_both")

    # strict: legacy "all cells correct/absent_both"
    doc_strict = sum(
        1 for fn, c_list in docs_seen.items()
        if fn in reviewed and all(_ok(c) for c in c_list)
    )
    doc_accuracy_strict = (
        doc_strict / n_reviewed_graded if n_reviewed_graded > 0 else 0.0
    )

    # smooth: mean over docs of (correct+absent_both)/total per doc
    graded_docs = [c_list for fn, c_list in docs_seen.items() if fn in reviewed]
    if graded_docs:
        doc_accuracy = sum(
            sum(1 for c in cs if _ok(c)) / len(cs)
            for cs in graded_docs
        ) / len(graded_docs)
    else:
        doc_accuracy = 0.0

    # without_array: same as smooth but skip cells where field.type == ARRAY
    array_field_names = {f.name for f in schema if f.type == FieldType.ARRAY}
    scalar_docs: list[list[CellVerdict]] = []
    for cs in graded_docs:
        scalar = [c for c in cs if c.field not in array_field_names]
        if scalar:
            scalar_docs.append(scalar)
    if scalar_docs:
        doc_accuracy_without_array = sum(
            sum(1 for c in cs if _ok(c)) / len(cs)
            for cs in scalar_docs
        ) / len(scalar_docs)
    else:
        # No array fields in schema (or no scalar cells) → identical to smooth.
        doc_accuracy_without_array = doc_accuracy

    return (
        per_field,
        field_accuracy_macro,
        doc_accuracy,
        doc_accuracy_without_array,
        doc_accuracy_strict,
        n_reviewed_graded,
    )


async def score(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    predictions: dict[str, list[dict[str, Any]]],
    reviewed: dict[str, list[dict[str, Any]]],
    *,
    use_llm_judge: bool = False,
    project_policy: AbsentPolicy = DEFAULT_PROJECT_POLICY,
) -> tuple[ScoreResultSummary, list[CellVerdict]]:
    """Orchestrate L1 + (L2) + L3 over reviewed × schema. Returns (summary, all_cells)."""

    cells: list[CellVerdict] = []
    errors: list[str] = []
    judge_used = 0
    judge_skipped_budget = 0

    l2_candidates: list[tuple[int, SchemaField, str, str]] = []

    for filename, reviewed_entities in reviewed.items():
        if filename not in predictions:
            errors.append(f"doc {filename} has reviewed but no prediction")
            for entity_idx, r_ent in enumerate(reviewed_entities):
                for field in schema:
                    rv = r_ent.get(field.name) if r_ent else None
                    policy = resolve_policy(field, project_policy)
                    if is_absent(rv, policy):
                        cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    else:
                        cells.append(_cell_missing(filename, entity_idx, field, rv))
            continue

        prediction_entities = predictions[filename]
        if len(prediction_entities) != len(reviewed_entities):
            errors.append(
                f"doc {filename}: predicted {len(prediction_entities)} entities, "
                f"reviewed {len(reviewed_entities)} — grading the overlap only"
            )

        max_idx = max(len(prediction_entities), len(reviewed_entities))
        for entity_idx in range(max_idx):
            r_ent = reviewed_entities[entity_idx] if entity_idx < len(reviewed_entities) else None
            p_ent = prediction_entities[entity_idx] if entity_idx < len(prediction_entities) else None

            for field in schema:
                policy = resolve_policy(field, project_policy)
                rv = r_ent.get(field.name) if r_ent else None
                pv = p_ent.get(field.name) if p_ent else None
                r_absent = is_absent(rv, policy) if r_ent is not None else True
                p_absent = is_absent(pv, policy) if p_ent is not None else True

                if r_absent and p_absent:
                    cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    continue

                if r_absent and not p_absent:
                    cells.append(_cell_spurious(filename, entity_idx, field, pv))
                    continue

                if not r_absent and p_absent:
                    cells.append(_cell_missing(filename, entity_idx, field, rv))
                    continue

                rv_s, pv_s = str(rv), str(pv)
                if rv_s == pv_s:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="exact",
                    ))
                    continue

                norm = normalize_equivalent(rv, pv, field)
                if norm.equivalent:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="normalize", normalizer=norm.normalizer,
                    ))
                    continue

                provisional = CellVerdict(
                    filename=filename, entity_idx=entity_idx, field=field.name,
                    status="wrong", truth=rv_s, pred=pv_s,
                    verdict_source="normalize", normalizer=norm.normalizer,
                )
                cells.append(provisional)
                if use_llm_judge:
                    l2_candidates.append((len(cells) - 1, field, rv_s, pv_s))

    if use_llm_judge and l2_candidates:
        verdicts, skipped = await judge_batch(
            workspace, project_id,
            [(f, t, p) for (_, f, t, p) in l2_candidates],
        )
        judge_skipped_budget = skipped
        for (cell_idx, _f, _t, _p), v in zip(l2_candidates, verdicts, strict=True):
            if v is None:
                continue
            judge_used += 1
            if v.equivalent:
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "status": "correct",
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })
            else:
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })

    (
        per_field,
        field_accuracy_macro,
        doc_accuracy,
        doc_accuracy_without_array,
        doc_accuracy_strict,
        n_reviewed,
    ) = _aggregate(cells, schema, reviewed)

    summary = ScoreResultSummary(
        n_docs=len(reviewed) + sum(1 for fn in predictions if fn not in reviewed),
        n_reviewed=n_reviewed,
        field_accuracy_macro=field_accuracy_macro,
        macro_f1=None,  # M12.x: F1 demoted; new writes no longer carry it.
        doc_accuracy=doc_accuracy,
        doc_accuracy_without_array=doc_accuracy_without_array,
        doc_accuracy_strict=doc_accuracy_strict,
        per_field=per_field,
        errors=errors,
        ts=_now_ts(),
        schema_field_count=len(schema),
        judge_used=judge_used,
        judge_skipped_budget=judge_skipped_budget,
    )
    return summary, cells


async def _load_pred_and_reviewed(
    workspace: Path, project_id: str, pd_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    predictions: dict[str, list[dict[str, Any]]] = {}
    reviewed: dict[str, list[dict[str, Any]]] = {}
    if pd_path.exists():
        for p in sorted(pd_path.glob("*.json")):
            blob = json.loads(p.read_text())
            predictions[p.stem] = blob.get("entities", [])
    rd = reviewed_dir(workspace, project_id)
    if rd.exists():
        for p in sorted(rd.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])
    return predictions, reviewed


def _write_cells_jsonl(path: Path, cells: list[CellVerdict]) -> None:
    lines = "\n".join(
        json.dumps(c.model_dump(mode="json"), ensure_ascii=False) for c in cells
    )
    path.write_text(lines + ("\n" if lines else ""), encoding="utf-8")


def _write_matrix_csv(
    path: Path, schema: list[SchemaField], cells: list[CellVerdict],
) -> None:
    path.write_text(cells_to_csv(schema, cells), encoding="utf-8")


def _write_meta(
    path: Path,
    workspace: Path,
    project_id: str,
    summary: ScoreResultSummary,
    experiment_id: Optional[str],
) -> None:
    try:
        blob = json.loads(project_json_path(workspace, project_id).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        blob = {}
    meta = {
        "prompt_id": blob.get("active_prompt_id"),
        "model_id": blob.get("active_model_id"),
        "experiment_id": experiment_id,
        "judge_used": summary.judge_used,
        "judge_skipped_budget": summary.judge_skipped_budget,
        "ts": summary.ts,
        "schema_field_count": summary.schema_field_count,
        "n_reviewed": summary.n_reviewed,
    }
    atomic_write_json(path, meta)


async def run_eval(
    workspace: Path,
    project_id: str,
    *,
    use_llm_judge: bool = False,
    experiment_id: Optional[str] = None,
) -> ScoreResultSummary:
    from app.tools.schema import read_schema
    from app.workspace.paths import experiment_predictions_dir

    _validate_project_id(project_id)

    schema = await read_schema(workspace, project_id)

    if experiment_id:
        pd_path = experiment_predictions_dir(workspace, project_id, experiment_id)
    else:
        pd_path = predictions_draft_dir(workspace, project_id)

    predictions, reviewed = await _load_pred_and_reviewed(
        workspace, project_id, pd_path,
    )
    summary, cells = await score(
        workspace, project_id, schema, predictions, reviewed,
        use_llm_judge=use_llm_judge,
    )

    async with project_lock(workspace, project_id):
        d = eval_dir(workspace, project_id, summary.ts)
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            eval_summary_path(workspace, project_id, summary.ts),
            summary.model_dump(mode="json"),
        )
        _write_cells_jsonl(
            eval_cells_path(workspace, project_id, summary.ts), cells,
        )
        _write_matrix_csv(
            eval_matrix_path(workspace, project_id, summary.ts),
            schema, cells,
        )
        _write_meta(
            eval_meta_path(workspace, project_id, summary.ts),
            workspace, project_id, summary, experiment_id,
        )
    return summary
