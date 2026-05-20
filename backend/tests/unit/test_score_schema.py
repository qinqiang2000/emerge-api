import pytest
from pydantic import ValidationError

from app.schemas.score import FieldScore, ScoreResult


def test_field_score_minimal() -> None:
    # M12.x — accuracy-first shape. F1 family fields are optional and default
    # to None; new writes only set the accuracy fields.
    f = FieldScore(
        field="invoice_no",
        accuracy=0.8421052631578948,
        correct=8, total=9, n_absent_both=0, not_applicable=False,
    )
    assert f.field == "invoice_no"
    assert f.correct == 8
    assert f.total == 9
    assert f.f1 is None
    assert f.tp is None


def test_field_score_legacy_shape_still_parses() -> None:
    """Old summaries on disk carry F1 family but no accuracy fields. The
    demoted-optional schema must still accept them so M12 vintage
    `metrics/eval_*.json` blobs load without errors."""
    f = FieldScore(
        field="x", tp=8, fp=1, fn=1, support=10,
        precision=8/9, recall=8/10, f1=0.8421052631578948,
    )
    assert f.field == "x"
    assert f.f1 == pytest.approx(0.842, rel=1e-3)
    assert f.accuracy is None
    assert f.correct == 0  # default
    assert f.total == 0


def test_score_result_aggregates() -> None:
    r = ScoreResult(
        n_docs=2,
        n_reviewed=2,
        field_accuracy_macro=0.92,
        macro_f1=None,
        per_field=[
            FieldScore(
                field="a", accuracy=1.0, correct=1, total=1,
                n_absent_both=0, not_applicable=False,
            ),
        ],
        errors=[],
        ts="2026-05-09T00-00-00Z",
        schema_field_count=1,
    )
    assert r.n_docs == 2
    assert r.field_accuracy_macro == 0.92
    assert r.macro_f1 is None
    assert len(r.per_field) == 1


def test_score_result_legacy_shape_still_parses() -> None:
    """Legacy summary on disk (pre-M12.x) carries `macro_f1` and no
    `field_accuracy_macro` — must still validate so /evals/latest can
    surface old runs."""
    r = ScoreResult(
        n_docs=1, n_reviewed=1, macro_f1=0.85,
        per_field=[], errors=[],
        ts="x", schema_field_count=1,
    )
    assert r.macro_f1 == 0.85
    assert r.field_accuracy_macro is None


def test_score_result_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ScoreResult(
            n_docs=0, n_reviewed=0, field_accuracy_macro=0.0,
            per_field=[], errors=[], ts="x", schema_field_count=0,
            unknown_field=1,
        )


def test_field_score_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        FieldScore(field="x", accuracy=0.0, unknown=1)
