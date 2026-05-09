from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.schema_field import SchemaField
from app.schemas.score import FieldScore, ScoreResult
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    metrics_dir,
    metrics_path,
    predictions_draft_dir,
    reviewed_dir,
    schema_path,
)


_PROJECT_ID = re.compile(r"^p_[a-z0-9]{12}$")


def _validate_project_id(project_id: str) -> None:
    if not _PROJECT_ID.match(project_id):
        raise ValueError("invalid project_id")


def _absent(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _eq(a: Any, b: Any) -> bool:
    return str(a).strip() == str(b).strip()


def _safe_div(a: float, b: float) -> float:
    return 0.0 if b == 0 else a / b


def _now_filename_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def score(
    schema: list[SchemaField],
    predictions: dict[str, list[dict[str, Any]]],
    reviewed: dict[str, list[dict[str, Any]]],
) -> ScoreResult:
    errors: list[str] = []
    counts = {field.name: {"tp": 0, "fp": 0, "fn": 0, "support": 0} for field in schema}

    n_reviewed_graded = 0
    for doc_id, reviewed_entities in reviewed.items():
        if doc_id not in predictions:
            errors.append(f"doc {doc_id} has reviewed but no prediction")
            continue
        prediction_entities = predictions[doc_id]
        # Multi-entity: pair by index. Mismatched lengths surface as errors
        # the user sees in the readiness checklist (Task 9).
        if len(prediction_entities) != len(reviewed_entities):
            errors.append(
                f"doc {doc_id}: predicted {len(prediction_entities)} entities, "
                f"reviewed {len(reviewed_entities)} — grading the overlap only"
            )
        n_reviewed_graded += 1
        pair_count = min(len(prediction_entities), len(reviewed_entities))
        for i in range(pair_count):
            reviewed_entity = reviewed_entities[i]
            prediction_entity = prediction_entities[i]
            for field in schema:
                reviewed_value = reviewed_entity.get(field.name)
                prediction_value = prediction_entity.get(field.name)
                reviewed_absent = _absent(reviewed_value)
                prediction_absent = _absent(prediction_value)

                if reviewed_absent and prediction_absent:
                    continue

                field_counts = counts[field.name]
                if not reviewed_absent:
                    field_counts["support"] += 1

                if not reviewed_absent and not prediction_absent:
                    if _eq(reviewed_value, prediction_value):
                        field_counts["tp"] += 1
                    else:
                        field_counts["fp"] += 1
                        field_counts["fn"] += 1
                elif reviewed_absent and not prediction_absent:
                    field_counts["fp"] += 1
                elif not reviewed_absent and prediction_absent:
                    field_counts["fn"] += 1

    per_field: list[FieldScore] = []
    for field in schema:
        field_counts = counts[field.name]
        tp = field_counts["tp"]
        fp = field_counts["fp"]
        fn = field_counts["fn"]
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_field.append(
            FieldScore(
                field=field.name,
                tp=tp,
                fp=fp,
                fn=fn,
                support=field_counts["support"],
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )

    macro_f1 = _safe_div(sum(field_score.f1 for field_score in per_field), len(per_field))

    return ScoreResult(
        n_docs=len(reviewed) + sum(1 for doc_id in predictions if doc_id not in reviewed),
        n_reviewed=n_reviewed_graded,
        macro_f1=macro_f1,
        per_field=per_field,
        errors=errors,
        ts=_now_filename_ts(),
        schema_field_count=len(schema),
    )


async def run_eval(workspace: Path, project_id: str) -> ScoreResult:
    _validate_project_id(project_id)

    schema_blob = json.loads(schema_path(workspace, project_id).read_text())
    schema = [SchemaField(**f) for f in schema_blob]

    predictions: dict[str, list[dict[str, Any]]] = {}
    pd = predictions_draft_dir(workspace, project_id)
    if pd.exists():
        for p in sorted(pd.glob("*.json")):
            blob = json.loads(p.read_text())
            predictions[p.stem] = blob.get("entities", [])

    reviewed: dict[str, list[dict[str, Any]]] = {}
    rd = reviewed_dir(workspace, project_id)
    if rd.exists():
        for p in sorted(rd.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])

    result = score(schema, predictions, reviewed)

    async with project_lock(workspace, project_id):
        metrics_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            metrics_path(workspace, project_id, f"eval_{result.ts}"),
            result.model_dump(mode="json"),
        )
    return result
