import json
from pathlib import Path

import pytest

from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.tools.score import run_eval, score
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import metrics_dir, predictions_draft_dir


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


async def test_run_eval_writes_metrics_file(workspace: Path) -> None:
    project_id = await create_project(workspace, name="eval")
    await write_schema(workspace, project_id, SCHEMA, reason="test", allow_structural=True)
    doc_id = await upload_doc(workspace, project_id, b"png", "sample.png")
    atomic_write_json(
        predictions_draft_dir(workspace, project_id) / f"{doc_id}.json",
        {"entities": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]},
    )
    await save_reviewed(
        workspace,
        project_id,
        doc_id,
        entities=[{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}],
        source=ReviewedSource.MANUAL,
    )

    result = await run_eval(workspace, project_id)

    assert result.n_reviewed == 1
    assert result.macro_f1 == 1.0
    files = list(metrics_dir(workspace, project_id).glob("eval_*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text())
    assert saved["macro_f1"] == 1.0


async def test_run_eval_with_no_reviewed_returns_zero_macro(workspace: Path) -> None:
    project_id = await create_project(workspace, name="eval-empty")
    await write_schema(workspace, project_id, SCHEMA, reason="test", allow_structural=True)

    result = await run_eval(workspace, project_id)

    assert result.n_reviewed == 0
    assert result.macro_f1 == 0.0
    assert metrics_dir(workspace, project_id).exists()


async def test_run_eval_rejects_invalid_project_id(workspace: Path) -> None:
    outside = workspace.parent / "outside"
    outside.mkdir()
    atomic_write_json(outside / "schema.json", [])

    with pytest.raises(ValueError, match="invalid project_id"):
        await run_eval(workspace, "../outside")

    assert not (outside / "metrics").exists()
