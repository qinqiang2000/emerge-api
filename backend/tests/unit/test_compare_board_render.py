"""对比报告白板 —— 口径与判据的回归锁（2026-08-20 compare-for-pm plan §3.2）。

这份报告是给不懂代码的产品经理读的，所以这里锁的不是「函数没崩」，而是几条
会直接改变她决策的性质：噪声不许被包装成结论、`n/a` 不许显示成 0%、没人标
required 时不许凭空多出一行 0% 的★指标。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import pytest

from app.tools.compare_board_render import (
    CompareError,
    render_compare_board,
)
from app.workspace.paths import eval_dir


def _field(
    name: str,
    *,
    correct: int = 0,
    absent_both: int = 0,
    wrong: int = 0,
    missing: int = 0,
    spurious: int = 0,
    required: bool = False,
) -> dict[str, Any]:
    """一行 FieldScore。`correct` 沿用打分器的口径：它**包含** absent_both。"""
    total = correct + wrong + missing + spurious
    nonempty_num = correct - absent_both
    nonempty_den = nonempty_num + wrong + missing
    return {
        "field": name,
        "accuracy": (correct / total) if total else 0.0,
        "correct": correct,
        "total": total,
        "n_absent_both": absent_both,
        "not_applicable": total == 0,
        "n_wrong": wrong,
        "n_missing": missing,
        "n_spurious": spurious,
        "accuracy_nonempty": (nonempty_num / nonempty_den) if nonempty_den else None,
        "required": required,
    }


def _write_eval(
    ws: Path,
    slug: str,
    ts: str,
    fields: list[dict[str, Any]],
    *,
    model: str = "gemini-2.5-flash",
    n_docs_perfect: int = 0,
    n_docs_graded: int = 10,
) -> None:
    num = sum(f["correct"] - f["n_absent_both"] for f in fields)
    den = sum(
        (f["correct"] - f["n_absent_both"]) + f["n_wrong"] + f["n_missing"]
        for f in fields
    )
    req = [f for f in fields if f["required"]]
    rnum = sum(f["correct"] - f["n_absent_both"] for f in req)
    rden = sum(
        (f["correct"] - f["n_absent_both"]) + f["n_wrong"] + f["n_missing"]
        for f in req
    )
    summary: dict[str, Any] = {
        "n_docs": n_docs_graded,
        "n_reviewed": n_docs_graded,
        "field_accuracy_macro": 0.9,
        "macro_f1": None,
        "doc_accuracy": 0.8,
        "doc_accuracy_strict": n_docs_perfect / n_docs_graded if n_docs_graded else 0.0,
        "cell_accuracy_nonempty": (num / den) if den else None,
        "required_cell_accuracy_nonempty": (rnum / rden) if rden else None,
        "n_docs_perfect": n_docs_perfect,
        "n_docs_graded": n_docs_graded,
        "n_required_fields": len(req),
        "per_field": fields,
        "errors": [],
        "ts": ts,
        "schema_field_count": len(fields),
        "extract_model": model,
    }
    d = eval_dir(ws, slug, ts)
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


TS_A = "2026-08-20T10-00-00Z"
TS_B = "2026-08-20T11-00-00Z"


async def test_clear_win_passes_both_gates(workspace: Path) -> None:
    """多对 20 格 + 20pp —— 两条线都跨过，才允许出现「建议换」。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=60, wrong=40)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=80, wrong=20)],
                model="gemini-3-flash")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "win"
    assert out["delta_cells"] == 20
    assert "建议换" in out["headline"]


async def test_big_pp_but_too_few_cells_is_noise(workspace: Path) -> None:
    """小样本陷阱：3 格 → 30pp 看着惊人，其实只多对 3 格。格数这条线拦住它。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=4, wrong=6)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=7, wrong=3)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "noise"
    assert "分不出高下" in out["headline"]
    assert "建议换" not in out["headline"]


async def test_many_cells_but_thin_pp_is_noise(workspace: Path) -> None:
    """大样本陷阱：多对 20 格但只有 2pp。百分点这条线拦住它。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=800, wrong=200)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=820, wrong=180)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "noise"
    assert out["delta_cells"] == 20
    assert "分不出高下" in out["headline"]


async def test_noise_headline_never_hedges_a_recommendation(workspace: Path) -> None:
    """噪声带内不许用「略优 / 倾向 / 更好」把结论包装出来 —— 这是本 plan 最贵的
    一条规则，产品经理照着这句话拍板。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=50, wrong=50)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=54, wrong=46)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "noise"
    for weasel in ("略优", "倾向", "更好", "建议换"):
        assert weasel not in out["headline"], f"headline hedged with {weasel!r}"


async def test_absent_both_cells_never_enter_the_nonempty_denominator(
    workspace: Path,
) -> None:
    """两边都空的送分格既不算对也不进分母 —— 否则罕见字段会把两侧都抬到 100%。"""
    # 100 格里 90 格两边都空，真正考到的只有 10 格（对 5 错 5）。
    _write_eval(workspace, "p", TS_A,
                [_field("f", correct=95, absent_both=90, wrong=5)])
    _write_eval(workspace, "p", TS_B,
                [_field("f", correct=95, absent_both=90, wrong=5)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    row = next(r for r in out["overall"] if r["label"] == "全字段 · 有值格")
    assert row["a"] == "50.0%", f"absent_both leaked into the headline: {row}"
    # 官方 macro 那一行仍然是送分口径，且必须带注解。
    macro = next(r for r in out["overall"] if "macro" in r["label"])
    assert "送分格" in macro["label"]


async def test_field_with_no_gt_values_renders_na_not_zero(workspace: Path) -> None:
    """GT 从来没有值的字段是「没考」，不是 0 分。"""
    fields = [_field("never", correct=10, absent_both=10), _field("real", correct=8, wrong=2)]
    _write_eval(workspace, "p", TS_A, fields)
    _write_eval(workspace, "p", TS_B, fields)

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    never = next(r for r in out["per_field"] if r["field"] == "never")
    assert never["a_acc"] is None and never["b_acc"] is None
    assert "n/a" in out["html"]
    assert ">0.0%<" not in out["html"].replace(" ", "")


async def test_star_row_omitted_when_nothing_is_marked_required(
    workspace: Path,
) -> None:
    """没人标 required → 整行省略，而不是凭空多出一行 0%。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=9, wrong=1)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert not any("★重要字段" in r["label"] for r in out["overall"])


async def test_star_row_present_and_micro_averaged_when_required_marked(
    workspace: Path,
) -> None:
    fields = [
        _field("important", correct=9, wrong=1, required=True),
        _field("minor", correct=1, wrong=9),
    ]
    _write_eval(workspace, "p", TS_A, fields)
    _write_eval(workspace, "p", TS_B, fields)

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    star = next(r for r in out["overall"] if "★重要字段" in r["label"])
    # 微平均：只看 important 那 10 格 → 90%。宏平均会是 (0.9+0.1)/2 = 50%。
    assert star["a"] == "90.0%"


async def test_mismatched_denominators_are_surfaced(workspace: Path) -> None:
    """一侧漏了预测（实体切分失败是常见原因）→ 静默按重叠打分会偏袒它。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=50, wrong=50)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=30, wrong=20)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert any("分母不同" in r["label"] for r in out["overall"])


async def test_perfect_docs_reported_as_n_over_n(workspace: Path) -> None:
    """「整篇零错 n/N」代替 doc_accuracy —— 它直接回答「几篇能免人工复核」。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)],
                n_docs_perfect=3, n_docs_graded=19)
    _write_eval(workspace, "p", TS_B, [_field("f", correct=9, wrong=1)],
                n_docs_perfect=11, n_docs_graded=19)

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    row = next(r for r in out["overall"] if r["label"] == "整篇零错文档")
    assert row["a"] == "3/19" and row["b"] == "11/19" and row["delta"] == "+8"


async def test_doc_accuracy_is_not_reported(workspace: Path) -> None:
    """`doc_accuracy` 会出现「0 篇全对却 84.4%」的自相矛盾读数，不上报告。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=9, wrong=1)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert not any("文档准确率" in r["label"] for r in out["overall"])
    assert "doc_accuracy" not in out["html"]


async def test_untrusted_field_names_are_escaped(workspace: Path) -> None:
    """字段名来自用户 schema —— 不可信数据一律 escape 才进 HTML。"""
    _write_eval(workspace, "p", TS_A, [_field("<script>x</script>", correct=8, wrong=2)])
    _write_eval(workspace, "p", TS_B, [_field("<script>x</script>", correct=9, wrong=1)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert "<script>x</script>" not in out["html"]
    assert "&lt;script&gt;" in out["html"]


async def test_missing_eval_raises_typed_error(workspace: Path) -> None:
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)])

    with pytest.raises(CompareError) as ei:
        await render_compare_board(workspace, "p", TS_A, TS_B)

    assert ei.value.error_code == "eval_not_found"


async def test_legacy_summary_without_new_keys_degrades_to_na(
    workspace: Path,
) -> None:
    """M12 时代的 `metrics/eval_<ts>/summary.json` 没有新键 —— 落到 n/a，
    不能崩、也不能报成 0%。"""
    for ts in (TS_A, TS_B):
        d = eval_dir(workspace, "p", ts)
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps({
            "n_docs": 5, "n_reviewed": 5,
            "field_accuracy_macro": 0.77, "doc_accuracy": 0.86,
            "per_field": [{"field": "f", "accuracy": 0.77, "correct": 7,
                           "total": 9, "n_absent_both": 0, "not_applicable": False}],
            "errors": [], "ts": ts, "schema_field_count": 1,
        }), encoding="utf-8")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    row = next(r for r in out["overall"] if r["label"] == "全字段 · 有值格")
    assert row["a"] == "n/a" and row["b"] == "n/a"
    # `stale`,不是 `noise` —— 见 test_stale_is_not_a_tie。
    assert out["verdict"] == "stale"


def test_side_label_prefers_semantic_name_over_ts() -> None:
    """报告里说 `gemini-3-flash`，不说 `2026-08-20T11-00-00Z` —— 产品经理读的是
    模型名（repo 惯例：id 只留给 plan 与运维脚本）。"""
    from app.schemas.score import ScoreResultSummary
    from app.tools.compare_board_render import _side_label

    s = ScoreResultSummary(
        n_docs=1, n_reviewed=1, per_field=[], errors=[], ts=TS_A,
        schema_field_count=0, extract_model="gemini-3-flash",
        prompt_label="Baseline v3",
    )
    label = _side_label(s, TS_A)
    assert "gemini-3-flash" in label and "Baseline v3" in label
    assert TS_A not in label


def test_side_label_falls_back_to_ts_when_unanchored() -> None:
    from app.schemas.score import ScoreResultSummary
    from app.tools.compare_board_render import _side_label

    s = ScoreResultSummary(n_docs=1, n_reviewed=1, per_field=[], errors=[],
                           ts=TS_A, schema_field_count=0)
    assert _side_label(s, TS_A) == TS_A


_ = Optional  # keep the import honest for the annotations above


# ── 无 GT 态（plan §4 T11）───────────────────────────────────────────────────
# `a`/`b` 是 prediction source 而不是 eval ts 时，白板转成分歧裁决清单。
# 这一态的红线只有一条，但它是整个 P3 的地基：**零百分比**。两个模型互相有多
# 一致不是准确率；一旦页面上并排出现两个百分数，读的人就会把它当准确率读走。

async def _no_gt_project(workspace: Path) -> str:
    from app.schemas.schema_field import FieldType, SchemaField
    from app.tools.projects import create_project
    from app.tools.schema import write_schema
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import experiment_predictions_dir, predictions_draft_dir

    slug = (await create_project(workspace, name="no-gt"))["slug"]
    await write_schema(workspace, slug, [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="d",
                    required=True),
        SchemaField(name="memo", type=FieldType.STRING, description="d"),
    ], reason="t", allow_structural=True)

    d = predictions_draft_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / "doc1.json", {
        "entities": [{"invoice_no": "A-1", "memo": "x"}]})

    e = experiment_predictions_dir(workspace, slug, "ex_abc123def456")
    e.mkdir(parents=True, exist_ok=True)
    atomic_write_json(e / "doc1.json", {
        "entities": [{"invoice_no": "A-2", "memo": "x"}]})
    return slug


async def test_no_gt_mode_reports_a_queue_not_a_score(workspace: Path) -> None:
    slug = await _no_gt_project(workspace)

    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert out["verdict"] == "no_gt"
    assert "分歧待裁决" in out["headline"]
    assert out["overall"] == [] and out["per_field"] == []
    assert out["n_diff"] == 1 and out["n_diff_required"] == 1


async def test_no_gt_html_contains_no_percentage_anywhere(workspace: Path) -> None:
    """红线锁：数据区不许出现任何百分数。(CSS 里的 `width: 100%` 不算 —— 断言
    只看渲染成单元格/正文的数字。)"""
    import re as _re

    slug = await _no_gt_project(workspace)
    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")
    body = out["html"].split("</style>", 1)[1]

    assert _re.search(r"\d+(\.\d+)?\s*%", body) is None, "a percentage leaked into the no-GT board"
    assert "pp" not in body.replace("<p", "").replace("</p", "")
    assert "准确率" in body  # 只在「这一页没有准确率」那句免责里出现
    assert "两个模型互相有多一致，不是准确率" in body


async def test_no_gt_shows_both_sides_raw_values(workspace: Path) -> None:
    """裁决人要看见对面到底写了什么，才能定夺。"""
    slug = await _no_gt_project(workspace)
    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert "A-1" in out["html"] and "A-2" in out["html"]


async def test_mixed_handles_are_refused(workspace: Path) -> None:
    """一侧 eval ts、一侧 prediction source —— 那是两种不同的问题，不许混着问。"""
    slug = await _no_gt_project(workspace)

    with pytest.raises(CompareError) as ei:
        await render_compare_board(workspace, slug, TS_A, "_draft")

    assert ei.value.error_code == "compare_mixed_handles"


async def test_identical_predictions_say_agreement_is_not_accuracy(
    workspace: Path,
) -> None:
    """两侧完全一致时最容易被读成「都对」。headline 必须点破。"""
    from app.schemas.schema_field import FieldType, SchemaField
    from app.tools.projects import create_project
    from app.tools.schema import write_schema
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import experiment_predictions_dir, predictions_draft_dir

    slug = (await create_project(workspace, name="same"))["slug"]
    await write_schema(workspace, slug, [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="d"),
    ], reason="t", allow_structural=True)
    for d in (predictions_draft_dir(workspace, slug),
              experiment_predictions_dir(workspace, slug, "ex_abc123def456")):
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(d / "doc1.json", {"entities": [{"invoice_no": "A-1"}]})

    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert out["n_diff"] == 0
    assert "一致不等于都对" in out["headline"]


async def test_legacy_blob_says_rerun_not_go_review(workspace: Path) -> None:
    """两种 None 的建议完全相反。生产 smoke 上撞到过：一个有 638 格 GT 的项目
    被告知「先做 review」，只因为它比的是 M12 时代打的分。"""
    for ts in (TS_A, TS_B):
        d = eval_dir(workspace, "p", ts)
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps({
            "n_docs": 19, "n_reviewed": 19,
            "field_accuracy_macro": 0.839, "doc_accuracy": 0.86,
            "per_field": [{"field": "f", "accuracy": 0.8, "correct": 8,
                           "total": 10, "n_absent_both": 0, "not_applicable": False}],
            "errors": [], "ts": ts, "schema_field_count": 1,
        }), encoding="utf-8")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert "重新跑一次评测" in out["headline"]
    assert "先给一些文档做 review" not in out["headline"]


async def test_truly_ungraded_project_says_go_review(workspace: Path) -> None:
    for ts in (TS_A, TS_B):
        d = eval_dir(workspace, "p", ts)
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps({
            "n_docs": 0, "n_reviewed": 0, "field_accuracy_macro": 0.0,
            "per_field": [], "errors": [], "ts": ts, "schema_field_count": 0,
        }), encoding="utf-8")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert "先给一些文档做 review" in out["headline"]


async def test_stale_is_not_a_tie(workspace: Path) -> None:
    """dogfood 抓到的：旧 blob 被标成 `noise`，前端 chip 于是显示「分不出高下」——
    可真相是「这两次评测该重跑」。说成打平是撒谎。"""
    for ts in (TS_A, TS_B):
        d = eval_dir(workspace, "p", ts)
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps({
            "n_docs": 19, "n_reviewed": 19, "field_accuracy_macro": 0.839,
            "per_field": [], "errors": [], "ts": ts, "schema_field_count": 0,
        }), encoding="utf-8")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "stale"
    # 副标题的篇数不能和 headline 打架（legacy blob 没有 n_docs_graded）。
    assert "0 篇" not in out["html"]
    assert "19 篇" in out["html"]


async def test_star_marks_only_the_required_row(workspace: Path) -> None:
    """dogfood 抓到的：★ 跑到了「全字段·有值格」那一行上，读的人会把它当成
    重要字段那档。总体表的「加粗」和逐字段表的「required」是两个意思。"""
    fields = [
        _field("important", correct=9, wrong=1, required=True),
        _field("minor", correct=5, wrong=5),
    ]
    _write_eval(workspace, "p", TS_A, fields)
    _write_eval(workspace, "p", TS_B, fields)

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    star_rows = [r for r in out["overall"] if r["css"] == "hard"]
    assert len(star_rows) == 1
    assert "★重要字段" in star_rows[0]["label"]
    whole = next(r for r in out["overall"] if r["label"] == "全字段 · 有值格")
    assert whole["css"] == "key", "the whole-schema row must not inherit the ★ class"


async def test_identical_labels_get_disambiguated(workspace: Path) -> None:
    """同一模型的两次跑批，标签会撞成「X vs X」，读不出谁是谁。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)], model="same-model")
    _write_eval(workspace, "p", TS_B, [_field("f", correct=9, wrong=1)], model="same-model")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["a_label"] != out["b_label"]
    assert TS_A in out["a_label"] and TS_B in out["b_label"]


async def test_distinct_labels_stay_clean(workspace: Path) -> None:
    """没撞就不补 ts —— 产品经理读的是模型名，时间戳是噪音。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=8, wrong=2)], model="gemini-2.5-flash")
    _write_eval(workspace, "p", TS_B, [_field("f", correct=9, wrong=1)], model="gemini-3-flash")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["a_label"] == "gemini-2.5-flash"
    assert TS_A not in out["a_label"]


async def test_no_gt_mode_names_the_models_not_the_ids(workspace: Path) -> None:
    """dogfood 抓到的：裁决态两侧显示成 `ex_6046df1xwwaa` vs `ex_7u4a2lh25dme`。
    产品经理读不出那是什么模型 —— 报告态早就读语义名了，这一态漏了。"""
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import experiment_meta_path

    slug = await _no_gt_project(workspace)
    mp = experiment_meta_path(workspace, slug, "ex_abc123def456")
    mp.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(mp, {"id": "ex_abc123def456", "label": "gemini-3-flash · Baseline"})

    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert out["b_label"] == "gemini-3-flash · Baseline"
    assert out["a_label"] == "当前配置（草稿）"
    assert "ex_abc123def456" not in out["html"]


async def test_no_gt_subtitle_does_not_claim_the_project_lacks_gt(
    workspace: Path,
) -> None:
    """dogfood 抓到的：对一个有 638 格 GT 的项目说「这个项目还没有 ground truth」。
    这个视图能被打开有两种原因，副标题只该描述自己在做什么。"""
    slug = await _no_gt_project(workspace)

    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert "这个项目还没有 ground truth" not in out["html"]
    assert "未对 ground truth 打分" in out["html"]


async def test_no_gt_detail_values_can_wrap(workspace: Path) -> None:
    """dogfood 抓到的：一个长地址就把「挑战者」那一列挤出视口。表格全局的
    `nowrap` 是给数字列定的，值列跟着遭殃 —— 而并排看两侧正是这张表的全部意义。"""
    from app.schemas.schema_field import FieldType, SchemaField
    from app.tools.projects import create_project
    from app.tools.schema import write_schema
    from app.workspace.atomic import atomic_write_json
    from app.workspace.paths import experiment_predictions_dir, predictions_draft_dir

    long_a = "BHPETROL Jln Klang Lama 4 Lot 35311 Batu 6 1/2, Jln Klang 58200, Wil. Persekutuan"
    slug = (await create_project(workspace, name="wide"))["slug"]
    await write_schema(workspace, slug, [
        SchemaField(name="billFromComposite", type=FieldType.STRING, description="d"),
    ], reason="t", allow_structural=True)
    d = predictions_draft_dir(workspace, slug)
    d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / "doc1.json", {"entities": [{"billFromComposite": long_a}]})
    e = experiment_predictions_dir(workspace, slug, "ex_abc123def456")
    e.mkdir(parents=True, exist_ok=True)
    atomic_write_json(e / "doc1.json", {"entities": [{"billFromComposite": "PETRON SEA PARK"}]})

    out = await render_compare_board(workspace, slug, "_draft", "ex_abc123def456")

    assert 'td.val { white-space: normal;' in out["html"]
    assert out["html"].count('<td class="val">') == 2, "both sides must use the wrapping column"


async def test_clearly_worse_challenger_is_not_called_a_tie(workspace: Path) -> None:
    """dogfood 抓到的：拿一个已知差很多的模型来比，得到「分不出高下，维持现状」。
    动作没错，但那句话是错的 —— 而人只记得住那句话。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=86, wrong=14)],
                model="gemini-2.5-flash")
    _write_eval(workspace, "p", TS_B, [_field("f", correct=63, wrong=37)],
                model="weak-model")

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "lose"
    assert "明显更差" in out["headline"] and "不要换" in out["headline"]
    assert "分不出高下" not in out["headline"]


async def test_lose_needs_both_thresholds_too(workspace: Path) -> None:
    """反方向也要两条线都跨过 —— 小幅落后同样是噪声，不能判「明显更差」。"""
    _write_eval(workspace, "p", TS_A, [_field("f", correct=54, wrong=46)])
    _write_eval(workspace, "p", TS_B, [_field("f", correct=50, wrong=50)])

    out = await render_compare_board(workspace, "p", TS_A, TS_B)

    assert out["verdict"] == "noise"
    assert "分不出高下" in out["headline"]


async def test_suffixed_ts_is_still_a_valid_eval_handle() -> None:
    """同秒碰撞加的 `-2Z` 后缀必须仍被认成 eval ts，否则第二份报告打不开。"""
    from app.tools.compare_board_render import is_eval_ts

    assert is_eval_ts("2026-08-21T05-46-53Z")
    assert is_eval_ts("2026-08-21T05-46-53-2Z")
    assert not is_eval_ts("_draft")
    assert not is_eval_ts("ex_6046df1xwwaa")
