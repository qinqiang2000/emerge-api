import pytest
from pydantic import ValidationError

from app.schemas.score import FieldScore, ScoreResult


def test_field_score_minimal() -> None:
    f = FieldScore(field="invoice_no", tp=8, fp=1, fn=1, support=10, precision=8/9, recall=8/10, f1=0.8421052631578948)
    assert f.field == "invoice_no"
    assert f.support == 10


def test_score_result_aggregates() -> None:
    r = ScoreResult(
        n_docs=2,
        n_reviewed=2,
        macro_f1=0.85,
        per_field=[
            FieldScore(field="a", tp=1, fp=0, fn=0, support=1, precision=1.0, recall=1.0, f1=1.0),
        ],
        errors=[],
        ts="2026-05-09T00-00-00Z",
        schema_field_count=1,
    )
    assert r.n_docs == 2
    assert r.macro_f1 == 0.85
    assert len(r.per_field) == 1


def test_score_result_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(
            n_docs=0, n_reviewed=0, macro_f1=0.0,
            per_field=[], errors=[], ts="x", schema_field_count=0,
            unknown_field=1,
        )


def test_field_score_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        FieldScore(field="x", tp=0, fp=0, fn=0, support=0, precision=0.0, recall=0.0, f1=0.0, unknown=1)
