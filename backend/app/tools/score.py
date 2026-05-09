from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.schema_field import SchemaField
from app.schemas.score import FieldScore, ScoreResult


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

        reviewed_entity = reviewed_entities[0] if reviewed_entities else {}
        prediction_entities = predictions[doc_id]
        prediction_entity = prediction_entities[0] if prediction_entities else {}
        n_reviewed_graded += 1

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
