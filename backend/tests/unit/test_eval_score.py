from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.eval.score import run_eval, score
from app.provider.base import ProviderResult
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
    metrics_dir,
    predictions_draft_dir,
)


def _f(name: str, t: FieldType = FieldType.STRING) -> SchemaField:
    return SchemaField(name=name, type=t, description="d")


SCHEMA = [_f("invoice_no"), _f("buyer_name"), _f("total", FieldType.NUMBER)]


async def test_score_perfect_match(workspace: Path) -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    summary, cells = await score(workspace, "p_x", SCHEMA, predictions, reviewed)
    assert summary.n_reviewed == 1
    # M12.x: `field_accuracy_macro` replaces `macro_f1` as the headline.
    assert summary.field_accuracy_macro == 1.0
    assert summary.macro_f1 is None
    assert summary.doc_accuracy == 1.0
    for fs in summary.per_field:
        assert fs.correct == 1
        assert fs.total == 1
        assert fs.n_absent_both == 0
        assert fs.not_applicable is False
        assert fs.accuracy == 1.0
        # F1 family is null on new writes.
        assert fs.f1 is None
        assert fs.tp is None


async def test_score_one_wrong_value(workspace: Path) -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "WRONG", "total": 100}]}
    summary, cells = await score(workspace, "p_x", SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in summary.per_field}
    assert by_field["invoice_no"].accuracy == 1.0
    assert by_field["buyer_name"].accuracy == 0.0
    assert by_field["total"].accuracy == 1.0
    assert summary.field_accuracy_macro == pytest.approx(2 / 3, rel=0.01)
    assert summary.doc_accuracy == 0.0  # doc is not fully correct


async def test_normalize_makes_number_correct(workspace: Path) -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": "123.10"}]}
    predictions = {"d_a": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": "123.1"}]}
    summary, cells = await score(workspace, "p_x", SCHEMA, predictions, reviewed)
    by_field = {fs.field: fs for fs in summary.per_field}
    assert by_field["total"].accuracy == 1.0
    assert by_field["total"].correct == 1
    assert summary.doc_accuracy == 1.0
    total_cell = next(c for c in cells if c.field == "total")
    assert total_cell.verdict_source == "normalize"
    assert total_cell.normalizer == "number"


async def test_exact_match_sets_verdict_source_exact(workspace: Path) -> None:
    reviewed = {"d_a": [{"invoice_no": "INV-1"}]}
    predictions = {"d_a": [{"invoice_no": "INV-1"}]}
    schema = [_f("invoice_no")]
    summary, cells = await score(workspace, "p_x", schema, predictions, reviewed)
    assert cells[0].verdict_source == "exact"


async def test_absent_policy_lenient_treats_null_as_absent_both(
    workspace: Path,
) -> None:
    # Default lenient: reviewed has b=None, pred omits b → absent_both.
    schema = [_f("a"), _f("b")]
    reviewed = {"d_a": [{"a": "1", "b": None}]}
    predictions = {"d_a": [{"a": "1"}]}
    summary, cells = await score(workspace, "p_x", schema, predictions, reviewed)
    b_cell = next(c for c in cells if c.field == "b")
    assert b_cell.status == "absent_both"
    assert b_cell.verdict_source == "presence"


async def test_absent_policy_strict_treats_empty_string_as_present(
    workspace: Path,
) -> None:
    schema = [SchemaField(name="a", type="string", description="d"),
              SchemaField(name="b", type="string", description="d",
                          absent_policy="strict")]
    reviewed = {"d_a": [{"a": "1", "b": ""}]}
    predictions = {"d_a": [{"a": "1", "b": "x"}]}
    summary, cells = await score(workspace, "p_x", schema, predictions, reviewed)
    b_cell = next(c for c in cells if c.field == "b")
    # Truth "" is present under strict (not absent); pred "x" is present; the
    # two differ → wrong (or spurious, depending on what _absent considers).
    # Under strict policy, "" is NOT absent; both are present; values differ
    # → mark as wrong with verdict_source=normalize.
    assert b_cell.status == "wrong"


async def test_multi_entity_mismatched_lengths_missing_cells(
    workspace: Path,
) -> None:
    schema = [_f("x")]
    reviewed = {"d_a": [{"x": "A"}, {"x": "B"}]}
    predictions = {"d_a": [{"x": "A"}]}
    summary, cells = await score(workspace, "p_x", schema, predictions, reviewed)
    # entity_idx 0 should be correct, entity_idx 1 should be missing
    by_idx = {(c.entity_idx, c.field): c for c in cells}
    assert by_idx[(0, "x")].status == "correct"
    assert by_idx[(1, "x")].status == "missing"
    assert any("grading the overlap only" in e for e in summary.errors)


async def test_use_llm_judge_upgrades_wrong_to_correct(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_obj = AsyncMock()
    provider_obj.extract = AsyncMock(return_value=ProviderResult(
        raw_json={"verdicts": [{"idx": 0, "equivalent": True, "reason": "syn"}]},
        model_id="stub", input_tokens=0, output_tokens=0,
    ))
    monkeypatch.setattr(
        "app.eval.judge.get_provider_for_model",
        lambda mid: provider_obj,
    )
    # An L1-disagreement: distinct strings, low fuzz ratio.
    schema = [_f("y")]
    reviewed = {"d_a": [{"y": "ACME Corp"}]}
    predictions = {"d_a": [{"y": "ACME Corporation"}]}
    summary, cells = await score(
        workspace, "p_x", schema, predictions, reviewed, use_llm_judge=True,
    )
    cell = cells[0]
    assert cell.status == "correct"
    assert cell.verdict_source == "llm_judge"
    assert cell.judge_reason == "syn"
    assert summary.judge_used == 1


async def test_use_llm_judge_budget_exhausted(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_obj = AsyncMock()
    provider_obj.extract = AsyncMock(return_value=ProviderResult(
        raw_json={"verdicts": []}, model_id="stub", input_tokens=0, output_tokens=0,
    ))
    monkeypatch.setattr(
        "app.eval.judge.get_provider_for_model",
        lambda mid: provider_obj,
    )
    monkeypatch.setenv("EMERGE_LLM_JUDGE_BUDGET_PER_EVAL", "1")
    schema = [_f("y")]
    # Two distinct L1-wrong cells; budget = 1 → 1 will be skipped.
    reviewed = {"d_a": [{"y": "AAA"}], "d_b": [{"y": "CCC"}]}
    predictions = {"d_a": [{"y": "BBB"}], "d_b": [{"y": "DDD"}]}
    summary, cells = await score(
        workspace, "p_x", schema, predictions, reviewed, use_llm_judge=True,
    )
    assert summary.judge_skipped_budget == 1


async def test_run_eval_writes_dir_artifact(workspace: Path) -> None:
    slug = (await create_project(workspace, name="dir-eval"))["slug"]
    await write_schema(workspace, slug, SCHEMA, reason="t", allow_structural=True)
    meta = await upload_doc(workspace, slug, b"\x89PNG\r\n\x1a\nstub", "x.png")
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(workspace, slug) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}]},
    )
    await save_reviewed(
        workspace, slug, filename,
        entities=[{"invoice_no": "INV-1", "buyer_name": "ACME", "total": 100}],
        source=ReviewedSource.MANUAL,
    )

    result = await run_eval(workspace, slug)
    assert result.n_reviewed == 1
    # M12.x: headline switched to field_accuracy_macro.
    assert result.field_accuracy_macro == 1.0
    assert result.macro_f1 is None
    assert result.doc_accuracy == 1.0

    d = eval_dir(workspace, slug, result.ts)
    assert d.exists()
    assert eval_summary_path(workspace, slug, result.ts).exists()
    assert eval_cells_path(workspace, slug, result.ts).exists()
    assert eval_matrix_path(workspace, slug, result.ts).exists()
    assert eval_meta_path(workspace, slug, result.ts).exists()

    summary_blob = json.loads(
        eval_summary_path(workspace, slug, result.ts).read_text()
    )
    assert summary_blob["field_accuracy_macro"] == 1.0
    assert summary_blob["doc_accuracy"] == 1.0

    # cells.jsonl content
    lines = eval_cells_path(workspace, slug, result.ts).read_text().splitlines()
    parsed = [json.loads(line) for line in lines]
    assert len(parsed) == 3  # 1 doc × 3 fields
    for cell in parsed:
        assert cell["status"] == "correct"

    # matrix.csv content
    matrix_text = eval_matrix_path(workspace, slug, result.ts).read_text()
    header = matrix_text.splitlines()[0]
    assert "filename" in header
    assert "·truth" in header
    assert "·pred" in header


async def test_run_eval_with_no_reviewed_returns_zero(workspace: Path) -> None:
    slug = (await create_project(workspace, name="empty"))["slug"]
    await write_schema(workspace, slug, SCHEMA, reason="t", allow_structural=True)
    result = await run_eval(workspace, slug)
    assert result.n_reviewed == 0
    # M12.x: when no fields are applicable (total=0 across all), macro is 0.
    assert result.field_accuracy_macro == 0.0
    assert result.doc_accuracy == 0.0
    assert metrics_dir(workspace, slug).exists()


async def test_accuracy_counts_absent_both(workspace: Path) -> None:
    """M12.x hard rule: a field where every reviewed cell is `absent_both`
    (model agreed with ground truth that the value is None) must come out
    as `accuracy=1.0`, not `0.0`. This is the dogfood landmine that drove
    M12.x — `invoice_code` on 默沙东_小票 had 21 absent_both cells and the
    old scorer reported F1=0, dragging the macro by ~5.9pp.
    """
    schema = [_f("invoice_code")]
    # 3 docs × 1 entity, all reviewed=None and pred omits the field
    # (defaults to None under lenient absent policy).
    reviewed = {
        "d_a": [{"invoice_code": None}],
        "d_b": [{"invoice_code": None}],
        "d_c": [{"invoice_code": None}],
    }
    predictions = {
        "d_a": [{}],
        "d_b": [{}],
        "d_c": [{}],
    }
    summary, cells = await score(workspace, "p_x", schema, predictions, reviewed)
    by_field = {fs.field: fs for fs in summary.per_field}
    fs = by_field["invoice_code"]
    assert fs.accuracy == 1.0, "absent_both must count as correct"
    assert fs.correct == 3
    assert fs.total == 3
    assert fs.n_absent_both == 3
    assert fs.not_applicable is False
    # Every cell verdict should be absent_both.
    assert all(c.status == "absent_both" for c in cells)
    # Macro should be 1.0 since the single applicable field is at 1.0.
    assert summary.field_accuracy_macro == 1.0


async def test_run_eval_rejects_invalid_project_id(workspace: Path) -> None:
    with pytest.raises(ValueError, match="invalid project_id"):
        await run_eval(workspace, "../outside")
