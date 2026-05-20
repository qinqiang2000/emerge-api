from pathlib import Path

from app.eval.types import CellStatus, CellVerdict, VerdictSource
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_judge_cache_dir,
    eval_judge_cache_path,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
)


def test_eval_dir(workspace: Path) -> None:
    assert eval_dir(workspace, "p_abc", "2026-05-21T00-00-00Z") == (
        workspace / "p_abc" / "metrics" / "eval_2026-05-21T00-00-00Z"
    )


def test_eval_summary_path(workspace: Path) -> None:
    assert eval_summary_path(workspace, "p_abc", "2026-05-21T00-00-00Z") == (
        workspace
        / "p_abc"
        / "metrics"
        / "eval_2026-05-21T00-00-00Z"
        / "summary.json"
    )


def test_eval_cells_path(workspace: Path) -> None:
    assert eval_cells_path(workspace, "p_abc", "2026-05-21T00-00-00Z") == (
        workspace
        / "p_abc"
        / "metrics"
        / "eval_2026-05-21T00-00-00Z"
        / "cells.jsonl"
    )


def test_eval_matrix_path(workspace: Path) -> None:
    assert eval_matrix_path(workspace, "p_abc", "2026-05-21T00-00-00Z") == (
        workspace
        / "p_abc"
        / "metrics"
        / "eval_2026-05-21T00-00-00Z"
        / "matrix.csv"
    )


def test_eval_meta_path(workspace: Path) -> None:
    assert eval_meta_path(workspace, "p_abc", "2026-05-21T00-00-00Z") == (
        workspace
        / "p_abc"
        / "metrics"
        / "eval_2026-05-21T00-00-00Z"
        / "meta.json"
    )


def test_eval_judge_cache_dir(workspace: Path) -> None:
    assert eval_judge_cache_dir(workspace, "p_abc") == (
        workspace / "p_abc" / ".eval_judge_cache"
    )


def test_eval_judge_cache_path(workspace: Path) -> None:
    sha = "deadbeef" * 8
    assert eval_judge_cache_path(workspace, "p_abc", sha) == (
        workspace / "p_abc" / ".eval_judge_cache" / f"{sha}.json"
    )


def test_cell_verdict_round_trip() -> None:
    cell = CellVerdict(
        filename="INV-001.pdf",
        entity_idx=0,
        field="tax_id",
        status="wrong",
        truth="123.10",
        pred="123.1",
        verdict_source="normalize",
        normalizer="number",
    )
    payload = cell.model_dump(mode="json")
    restored = CellVerdict(**payload)
    assert restored == cell


def test_cell_verdict_minimal_absent_both() -> None:
    cell = CellVerdict(
        filename="INV-001.pdf",
        entity_idx=0,
        field="tax_id",
        status="absent_both",
        verdict_source="presence",
    )
    assert cell.truth is None
    assert cell.pred is None
    assert cell.normalizer is None
    assert cell.judge_reason is None
    assert cell.judge_model is None


def test_cell_status_and_verdict_source_literals() -> None:
    valid_status: list[CellStatus] = [
        "correct",
        "wrong",
        "missing",
        "spurious",
        "absent_both",
    ]
    valid_source: list[VerdictSource] = [
        "exact",
        "normalize",
        "llm_judge",
        "presence",
    ]
    assert len(valid_status) == 5
    assert len(valid_source) == 4
