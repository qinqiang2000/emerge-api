"""M-compare —「GT 有值格」口径的锁。

口径真相（唯一一份，别在别处再写一遍）：

    GT 有值格 = status ∈ {correct, wrong, missing}
    GT 空格   = status ∈ {absent_both, spurious}
    有值格准确率 = correct / (correct + wrong + missing)

这一族测试盯的是最容易写错的两处：分子别混进 absent_both（`_aggregate`
里 absent_both 会同时给 `correct` 计数，那是 accuracy-first 口径的分子，
不是这一档的），分母为 0 时给 `None` 而不是 0.0。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.eval.score import _aggregate, score
from app.eval.types import CellStatus, CellVerdict
from app.schemas.schema_field import FieldType, SchemaField
from app.schemas.score import ScoreResultSummary


def _f(name: str, *, required: bool = False) -> SchemaField:
    return SchemaField(
        name=name, type=FieldType.STRING, description="d", required=required,
    )


def _cells(
    field: str, spec: dict[CellStatus, int], *, filename: str = "d_a",
) -> list[CellVerdict]:
    """按 {status: 次数} 摊平成 cells，entity_idx 递增只为满足模型形状。"""
    out: list[CellVerdict] = []
    for status, n in spec.items():
        for _ in range(n):
            out.append(CellVerdict(
                filename=filename, entity_idx=len(out), field=field,
                status=status, verdict_source="presence",
            ))
    return out


def test_nonempty_denominator_excludes_absent_both_and_spurious() -> None:
    schema = [_f("a")]
    cells = _cells("a", {
        "correct": 2, "wrong": 1, "missing": 1,
        "spurious": 3, "absent_both": 4,
    })
    agg = _aggregate(cells, schema, {"d_a": [{}]})
    fs = agg.per_field[0]

    # 五档都单独记上了。
    assert (fs.n_wrong, fs.n_missing, fs.n_spurious, fs.n_absent_both) == (1, 1, 3, 4)
    assert fs.total == 11

    # accuracy-first 口径不变：absent_both 仍算对（2 + 4）/11。
    assert fs.correct == 6
    assert fs.accuracy == pytest.approx(6 / 11)

    # 有值格：分母只有 2+1+1=4（spurious 的 3 格、absent_both 的 4 格都出局），
    # 分子只有 status=="correct" 的 2 格 —— 不是 `fs.correct` 的 6。
    assert fs.accuracy_nonempty == pytest.approx(2 / 4)
    assert agg.cell_accuracy_nonempty == pytest.approx(2 / 4)


def test_all_absent_both_field_is_none_not_zero() -> None:
    """全是 absent_both 的字段：`None`，而且不许拉低全局微平均。"""
    schema = [_f("a"), _f("b")]
    cells = _cells("a", {"correct": 3}) + _cells("b", {"absent_both": 5})
    agg = _aggregate(cells, schema, {"d_a": [{}]})
    by_field = {p.field: p for p in agg.per_field}

    assert by_field["b"].accuracy_nonempty is None  # 不是 0.0
    assert by_field["a"].accuracy_nonempty == pytest.approx(1.0)
    # 微平均 = Σ分子/Σ分母 = 3/3。b 一格都没进分母，所以既不是 0.5（把 b
    # 当 0% 的宏平均）也不是 3/8（把 absent_both 塞进分母）。
    assert agg.cell_accuracy_nonempty == pytest.approx(1.0)


def test_no_required_fields_yields_none_not_zero() -> None:
    schema = [_f("a"), _f("b")]
    cells = _cells("a", {"correct": 1, "wrong": 1}) + _cells("b", {"correct": 2})
    agg = _aggregate(cells, schema, {"d_a": [{}]})

    assert agg.n_required_fields == 0
    # ★行整行隐藏靠这个 None，报成 0% 会让 PM 以为必填字段全错。
    assert agg.required_cell_accuracy_nonempty is None
    assert all(p.required is False for p in agg.per_field)


def test_required_subset_is_cell_micro_not_field_macro() -> None:
    schema = [_f("a", required=True), _f("b", required=True), _f("c")]
    cells = (
        _cells("a", {"correct": 9, "wrong": 1})     # 9/10
        + _cells("b", {"correct": 0, "wrong": 2})   # 0/2
        + _cells("c", {"correct": 100})             # 非必填，不进 ★ 行
    )
    agg = _aggregate(cells, schema, {"d_a": [{}]})

    assert agg.n_required_fields == 2
    assert [p.required for p in agg.per_field] == [True, True, False]
    # 微平均 9/12，不是宏平均 (0.9+0.0)/2=0.45。
    assert agg.required_cell_accuracy_nonempty == pytest.approx(9 / 12)
    assert agg.cell_accuracy_nonempty == pytest.approx(109 / 112)


def test_docs_perfect_over_graded_matches_strict_ratio() -> None:
    """`n_docs_perfect / n_docs_graded` 就是 `doc_accuracy_strict` 的原料。"""
    schema = [_f("a")]
    cells = (
        _cells("a", {"correct": 1, "absent_both": 1}, filename="d_ok")
        + _cells("a", {"correct": 1, "wrong": 1}, filename="d_bad")
        + _cells("a", {"missing": 1}, filename="d_worse")
    )
    reviewed = {"d_ok": [{}], "d_bad": [{}], "d_worse": [{}]}
    agg = _aggregate(cells, schema, reviewed)

    assert agg.n_docs_perfect == 1
    assert agg.n_reviewed_graded == 3
    assert agg.doc_accuracy_strict == pytest.approx(
        agg.n_docs_perfect / agg.n_reviewed_graded
    )


def test_legacy_summary_without_new_keys_still_parses() -> None:
    """磁盘上的历史 `metrics/eval_*/summary.json`：一个新键都没有，
    `extra="forbid"` 只挡多余键，缺键必须靠默认值兜住。"""
    legacy = {
        "n_docs": 2,
        "n_reviewed": 2,
        "field_accuracy_macro": 0.92,
        "macro_f1": None,
        "doc_accuracy": 0.9,
        "doc_accuracy_strict": 0.5,
        "per_field": [
            {
                "field": "a", "accuracy": 0.92, "correct": 11, "total": 12,
                "n_absent_both": 1, "not_applicable": False,
                "tp": None, "fp": None, "fn": None, "support": None,
                "precision": None, "recall": None, "f1": None,
            },
        ],
        "errors": [],
        "ts": "2026-05-09T00-00-00Z",
        "schema_field_count": 1,
        "judge_used": 0,
        "judge_skipped_budget": 0,
    }
    s = ScoreResultSummary.model_validate(legacy)

    assert s.field_accuracy_macro == 0.92
    assert s.cell_accuracy_nonempty is None
    assert s.required_cell_accuracy_nonempty is None
    assert s.n_docs_perfect is None
    assert s.n_docs_graded is None
    assert s.n_required_fields is None
    fs = s.per_field[0]
    assert (fs.n_wrong, fs.n_missing, fs.n_spurious) == (0, 0, 0)
    assert fs.accuracy_nonempty is None
    assert fs.required is False


async def test_summary_carries_nonempty_metrics_end_to_end(workspace: Path) -> None:
    """走完整 `score()`，确认新口径真的落进 summary（而不只是 `_aggregate`
    的返回值）。b 全空是送分格：官方 macro 看着高，有值格口径不给分。"""
    schema = [_f("a", required=True), _f("b")]
    reviewed = {
        "d_1": [{"a": "X"}],
        "d_2": [{"a": "Y"}],
    }
    predictions = {
        "d_1": [{"a": "X"}],
        "d_2": [{"a": "ZZ"}],
    }
    summary, _cells_out = await score(
        workspace, "p_x", schema, predictions, reviewed,
    )

    assert summary.n_required_fields == 1
    assert summary.n_docs_graded == 2
    assert summary.n_docs_perfect == 1
    # a：1 对 1 错 → 0.5。b：两篇都两边都空 → 一格都不进分母。
    assert summary.cell_accuracy_nonempty == pytest.approx(0.5)
    assert summary.required_cell_accuracy_nonempty == pytest.approx(0.5)
    by_field = {p.field: p for p in summary.per_field}
    assert by_field["b"].accuracy_nonempty is None
    assert by_field["b"].accuracy == pytest.approx(1.0)  # 送分格照旧给分


# ── 同秒碰撞（2026-08-21 dogfood）─────────────────────────────────────────
# `ts` 只到秒。以前够用：一次 eval 要调几分钟 LLM。但复用已有预测重打分只要
# ~200ms，连着给三个模型打分会全落在同一秒 —— 后面的把前面的 summary/cells
# 直接覆盖掉，三个模型只剩一份结果。

async def test_same_second_evals_do_not_clobber_each_other(
    workspace: Path, monkeypatch,
) -> None:
    import json as _json

    from app.eval import score as score_mod
    from app.schemas.schema_field import FieldType, SchemaField
    from app.tools.projects import create_project
    from app.tools.schema import write_schema
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import (
        eval_summary_path, predictions_draft_dir, reviewed_dir,
    )

    # 时钟钉死在同一秒 —— 这正是复用预测重打分时的真实情形。
    monkeypatch.setattr(score_mod, "_now_ts", lambda: "2026-08-21T05-46-53Z")

    slug = (await create_project(workspace, name="clash"))["slug"]
    await write_schema(workspace, slug, [
        SchemaField(name="f", type=FieldType.STRING, description="d"),
    ], reason="t", allow_structural=True)

    rd = reviewed_dir(workspace, slug)
    rd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(rd / "doc1.json", {"entities": [{"f": "right"}]})
    pd = predictions_draft_dir(workspace, slug)
    pd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pd / "doc1.json", {"entities": [{"f": "right"}]})

    first = await score_mod.run_eval(workspace, slug)

    # 第二次同秒打分，但预测换了内容 —— 两份结果必须都留在盘上。
    atomic_write_json(pd / "doc1.json", {"entities": [{"f": "wrong"}]})
    second = await score_mod.run_eval(workspace, slug)

    assert first.ts != second.ts, "the second eval reused the first one's ts"
    a = _json.loads(eval_summary_path(workspace, slug, first.ts).read_text())
    b = _json.loads(eval_summary_path(workspace, slug, second.ts).read_text())
    assert a["cell_accuracy_nonempty"] == 1.0, "the first eval got clobbered"
    assert b["cell_accuracy_nonempty"] == 0.0
