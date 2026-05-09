import pytest

from app.schemas.schema_field import FieldType, SchemaField
from app.tools.score import score


def _f(name: str, t: FieldType = FieldType.STRING) -> SchemaField:
    return SchemaField(name=name, type=t, description="d")


SCHEMA = [_f("invoice_no"), _f("buyer_name"), _f("total")]


def test_score_perfect_match() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    r = score(SCHEMA, predictions, reviewed)
    assert r.n_reviewed == 1
    assert r.macro_f1 == 1.0
    for fs in r.per_field:
        assert fs.tp == 1
        assert fs.fp == 0
        assert fs.fn == 0
        assert fs.f1 == 1.0


def test_score_one_wrong_value() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "WRONG", "total": 100}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    assert by_field["invoice_no"].f1 == 1.0
    assert by_field["buyer_name"].f1 == 0.0
    assert by_field["total"].f1 == 1.0
    assert r.macro_f1 == pytest.approx(2 / 3, rel=0.01)


def test_score_missing_prediction_field() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "total": 100}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    assert bn.tp == 0
    assert bn.fn == 1
    assert bn.fp == 0


def test_score_extra_prediction_field() -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1"}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "GUESS"}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    assert bn.fp == 1
    assert bn.fn == 0
    assert bn.tp == 0


def test_score_skips_doc_without_prediction() -> None:
    reviewed = {"d_a": [{"invoice_no": "X"}], "d_b": [{"invoice_no": "Y"}]}
    predictions = {"d_a": [{"invoice_no": "X"}]}
    r = score(SCHEMA, predictions, reviewed)
    assert r.n_reviewed == 1
    assert any("d_b" in e for e in r.errors)


def test_score_empty_reviewed_returns_zeros() -> None:
    r = score(SCHEMA, {}, {})
    assert r.n_reviewed == 0
    assert r.macro_f1 == 0.0
    for fs in r.per_field:
        assert fs.tp == fs.fp == fs.fn == 0


def test_score_treats_empty_string_and_none_as_absent() -> None:
    reviewed = {"d_a": [{"invoice_no": "X", "buyer_name": ""}]}
    predictions = {"d_a": [{"invoice_no": "X", "buyer_name": None}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    bn = by_field["buyer_name"]
    assert bn.tp == bn.fp == bn.fn == 0


def test_score_strings_compared_after_strip_and_str_cast() -> None:
    reviewed = {"d_a": [{"total": 100}]}
    predictions = {"d_a": [{"total": "100 "}]}
    r = score(SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in r.per_field}
    assert by_field["total"].tp == 1
