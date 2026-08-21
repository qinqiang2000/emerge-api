from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple, Optional

from app.eval.judge import judge_batch
from app.eval.normalize import normalize_equivalent
from app.eval.pivot import cells_to_csv
from app.eval.presence import (
    DEFAULT_PROJECT_POLICY,
    AbsentPolicy,
    is_absent,
    resolve_policy,
)
from app.eval.types import CellVerdict
from app.schemas.schema_field import SchemaField
from app.schemas.score import FieldScore, ScoreResultSummary
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    eval_cells_path,
    eval_dir,
    eval_matrix_path,
    eval_meta_path,
    eval_summary_path,
    predictions_draft_dir,
    project_json_path,
    reviewed_dir,
)


def _validate_project_id(project_id: str) -> None:
    if (
        not isinstance(project_id, str)
        or not project_id
        or "/" in project_id
        or "\\" in project_id
        or project_id in (".", "..")
        or "\x00" in project_id
    ):
        raise ValueError("invalid project_id")


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def _str_or_none(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _cell_absent_both(filename: str, entity_idx: int, field_name: str) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field_name,
        status="absent_both", verdict_source="presence",
    )


def _cell_missing(filename: str, entity_idx: int, field: SchemaField, truth_v: Any) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field.name,
        status="missing", truth=_str_or_none(truth_v),
        verdict_source="presence",
    )


def _cell_spurious(filename: str, entity_idx: int, field: SchemaField, pred_v: Any) -> CellVerdict:
    return CellVerdict(
        filename=filename, entity_idx=entity_idx, field=field.name,
        status="spurious", pred=_str_or_none(pred_v),
        verdict_source="presence",
    )


class AggregateResult(NamedTuple):
    """`_aggregate` 的返回面。

    原来是 5-tuple，M-compare 加了格级口径后装不下了。全仓只有一个调用点
    （下面的 `score`），换成 NamedTuple 零成本 —— 而且 `app/eval/` 的邻居
    （`NormalizeResult` / `JudgeVerdict`）本来就是这个形状。
    """

    per_field: list[FieldScore]
    field_accuracy_macro: float
    doc_accuracy: float
    doc_accuracy_strict: float
    n_reviewed_graded: int
    # ── M-compare：GT 有值格口径（格级微平均），下面 docstring 有为什么。
    cell_accuracy_nonempty: Optional[float]
    required_cell_accuracy_nonempty: Optional[float]
    n_required_fields: int
    n_docs_perfect: int


def _aggregate(
    cells: list[CellVerdict],
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
) -> AggregateResult:
    """M12.x — accuracy-first aggregation.

    Per-field `accuracy = (correct + absent_both) / total`. The model nailing
    "this field has no value" (absent_both) is a correct prediction, not a
    non-event. F1/precision/recall are no longer computed in the hot path —
    emitted as `None` so legacy summaries still validate via the demoted
    optional schema, but new writes don't carry stale F1 numbers.

    `not_applicable=True` when `total==0` (defensive — schema has the field
    but no entity ever exposed it). Macro accuracy excludes these.

    M12.x.c — two doc-level numbers:
      * `doc_accuracy` (smooth): mean over graded docs of
        (correct + absent_both) / total_cells_in_doc. Replaces the brittle
        all-or-nothing strict number as the new headline.
      * `doc_accuracy_strict` (legacy): the old "all cells correct/absent_both"
        definition, kept for "is this doc 100% perfect?" signal.

    M-compare — 另起一档「GT 有值格」口径，给对比报告当头条：

        GT 有值格 = status ∈ {correct, wrong, missing}
        GT 空格   = status ∈ {absent_both, spurious}
        有值格准确率 = correct / (correct + wrong + missing)

    为什么要另起一档：上面那条 accuracy-first 把 absent_both 算进分子，
    对「模型知道这里没有」是公平的，但两边都空是送分题 —— 字段越稀疏分
    数越好看，拿它比两个模型会比出噪声。有值格口径把送分区整段剔掉。

    两个坑，都写死在这：
      1. 分子只数 `status == "correct"`，**不含** absent_both —— 那些格
         压根不在这个分母里，混进来送分题就又漏回来了。
      2. 分母为 0 时是 `None` 而不是 0.0 —— 「这个字段没有可判的有值格」
         和「有值格全错」必须能分开（同 `not_applicable` 那条红线）。

    全局数是**格级微平均**（Σ分子 / Σ分母），不是字段级宏平均：宏平均让
    「22 格全空的稀有字段」和「每篇都有的主键字段」等权，会被拉偏。既有
    的 `field_accuracy_macro`（宏平均）语义原样不动，publish gate 还压在
    它身上。
    """
    counts: dict[str, dict[str, int]] = {
        f.name: {
            "correct": 0, "total": 0, "absent_both": 0,
            # 五档分状态计数。`correct_nonempty` 单开一格，是因为 `correct`
            # 里混了 absent_both（见循环里的注释）——有值格口径的分子不能
            # 从 `correct` 减出来，那正是最容易写错的地方。
            "correct_nonempty": 0, "wrong": 0, "missing": 0, "spurious": 0,
        }
        for f in schema
    }
    for c in cells:
        if c.field not in counts:
            continue
        d = counts[c.field]
        d["total"] += 1
        if c.status == "correct":
            d["correct"] += 1
            d["correct_nonempty"] += 1
        elif c.status == "absent_both":
            # The hard rule: model agreed there's nothing here, ground truth
            # agreed there's nothing here — that's a correct prediction.
            # 只进 `correct`，不进 `correct_nonempty`。
            d["correct"] += 1
            d["absent_both"] += 1
        elif c.status in ("wrong", "missing", "spurious"):
            d[c.status] += 1

    def _nonempty_total(d: dict[str, int]) -> int:
        # spurious 不进分母：GT 空、模型多填 —— 那衡量的是「乱填」，不是
        # 「有值的地方抽得准不准」。
        return d["correct_nonempty"] + d["wrong"] + d["missing"]

    per_field: list[FieldScore] = []
    for f in schema:
        d = counts[f.name]
        not_applicable = d["total"] == 0
        accuracy = (d["correct"] / d["total"]) if d["total"] > 0 else 0.0
        nonempty_total = _nonempty_total(d)
        per_field.append(FieldScore(
            field=f.name,
            correct=d["correct"],
            total=d["total"],
            n_absent_both=d["absent_both"],
            not_applicable=not_applicable,
            accuracy=accuracy,
            # M-compare 分档计数 + 有值格准确率。
            n_wrong=d["wrong"],
            n_missing=d["missing"],
            n_spurious=d["spurious"],
            accuracy_nonempty=(
                d["correct_nonempty"] / nonempty_total
                if nonempty_total > 0 else None
            ),
            required=bool(f.required),
            # F1 family deliberately None on new writes.
            tp=None, fp=None, fn=None, support=None,
            precision=None, recall=None, f1=None,
        ))

    applicable = [p for p in per_field if not p.not_applicable]
    field_accuracy_macro = (
        sum(p.accuracy or 0.0 for p in applicable) / len(applicable)
        if applicable else 0.0
    )

    def _micro(fields: list[SchemaField]) -> Optional[float]:
        """格级微平均：先把分子分母各自加总，再相除。"""
        num = sum(counts[f.name]["correct_nonempty"] for f in fields)
        den = sum(_nonempty_total(counts[f.name]) for f in fields)
        return (num / den) if den > 0 else None

    # `required` 在此之前是纯文档字段（`app/tools/extract.py` 明说不 enforce）；
    # M-compare 起它有了第一个语义消费者：★重要字段那一行的过滤器。
    required_fields = [f for f in schema if f.required]
    cell_accuracy_nonempty = _micro(schema)
    required_cell_accuracy_nonempty = _micro(required_fields)

    docs_seen: dict[str, list[CellVerdict]] = {}
    for c in cells:
        docs_seen.setdefault(c.filename, []).append(c)
    n_reviewed_graded = sum(1 for fn in reviewed if fn in docs_seen)

    def _ok(c: CellVerdict) -> bool:
        return c.status in ("correct", "absent_both")

    # strict: legacy "all cells correct/absent_both"
    doc_strict = sum(
        1 for fn, c_list in docs_seen.items()
        if fn in reviewed and all(_ok(c) for c in c_list)
    )
    doc_accuracy_strict = (
        doc_strict / n_reviewed_graded if n_reviewed_graded > 0 else 0.0
    )

    # smooth: mean over docs of (correct+absent_both)/total per doc
    graded_docs = [c_list for fn, c_list in docs_seen.items() if fn in reviewed]
    if graded_docs:
        doc_accuracy = sum(
            sum(1 for c in cs if _ok(c)) / len(cs)
            for cs in graded_docs
        ) / len(graded_docs)
    else:
        doc_accuracy = 0.0

    return AggregateResult(
        per_field=per_field,
        field_accuracy_macro=field_accuracy_macro,
        doc_accuracy=doc_accuracy,
        doc_accuracy_strict=doc_accuracy_strict,
        n_reviewed_graded=n_reviewed_graded,
        cell_accuracy_nonempty=cell_accuracy_nonempty,
        required_cell_accuracy_nonempty=required_cell_accuracy_nonempty,
        n_required_fields=len(required_fields),
        # 「整篇零错」的分子/分母本来就算好了，之前只对外给了比值。报告要的
        # 是 n/N 这种 PM 读得懂的数，不是又一个百分比。
        n_docs_perfect=doc_strict,
    )


async def score(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    predictions: dict[str, list[dict[str, Any]]],
    reviewed: dict[str, list[dict[str, Any]]],
    *,
    use_llm_judge: bool = False,
    project_policy: AbsentPolicy = DEFAULT_PROJECT_POLICY,
) -> tuple[ScoreResultSummary, list[CellVerdict]]:
    """Orchestrate L1 + (L2) + L3 over reviewed × schema. Returns (summary, all_cells)."""

    cells: list[CellVerdict] = []
    errors: list[str] = []
    judge_used = 0
    judge_skipped_budget = 0

    l2_candidates: list[tuple[int, SchemaField, str, str]] = []

    for filename, reviewed_entities in reviewed.items():
        if filename not in predictions:
            errors.append(f"doc {filename} has reviewed but no prediction")
            for entity_idx, r_ent in enumerate(reviewed_entities):
                for field in schema:
                    rv = r_ent.get(field.name) if r_ent else None
                    policy = resolve_policy(field, project_policy)
                    if is_absent(rv, policy):
                        cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    else:
                        cells.append(_cell_missing(filename, entity_idx, field, rv))
            continue

        prediction_entities = predictions[filename]
        if len(prediction_entities) != len(reviewed_entities):
            errors.append(
                f"doc {filename}: predicted {len(prediction_entities)} entities, "
                f"reviewed {len(reviewed_entities)} — grading the overlap only"
            )

        max_idx = max(len(prediction_entities), len(reviewed_entities))
        for entity_idx in range(max_idx):
            r_ent = reviewed_entities[entity_idx] if entity_idx < len(reviewed_entities) else None
            p_ent = prediction_entities[entity_idx] if entity_idx < len(prediction_entities) else None

            for field in schema:
                policy = resolve_policy(field, project_policy)
                rv = r_ent.get(field.name) if r_ent else None
                pv = p_ent.get(field.name) if p_ent else None
                r_absent = is_absent(rv, policy) if r_ent is not None else True
                p_absent = is_absent(pv, policy) if p_ent is not None else True

                if r_absent and p_absent:
                    cells.append(_cell_absent_both(filename, entity_idx, field.name))
                    continue

                if r_absent and not p_absent:
                    cells.append(_cell_spurious(filename, entity_idx, field, pv))
                    continue

                if not r_absent and p_absent:
                    cells.append(_cell_missing(filename, entity_idx, field, rv))
                    continue

                rv_s, pv_s = str(rv), str(pv)
                if rv_s == pv_s:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="exact",
                    ))
                    continue

                norm = normalize_equivalent(rv, pv, field)
                if norm.equivalent:
                    cells.append(CellVerdict(
                        filename=filename, entity_idx=entity_idx, field=field.name,
                        status="correct", truth=rv_s, pred=pv_s,
                        verdict_source="normalize", normalizer=norm.normalizer,
                    ))
                    continue

                provisional = CellVerdict(
                    filename=filename, entity_idx=entity_idx, field=field.name,
                    status="wrong", truth=rv_s, pred=pv_s,
                    verdict_source="normalize", normalizer=norm.normalizer,
                )
                cells.append(provisional)
                if use_llm_judge:
                    l2_candidates.append((len(cells) - 1, field, rv_s, pv_s))

    if use_llm_judge and l2_candidates:
        verdicts, skipped = await judge_batch(
            workspace, project_id,
            [(f, t, p) for (_, f, t, p) in l2_candidates],
        )
        judge_skipped_budget = skipped
        for (cell_idx, _f, _t, _p), v in zip(l2_candidates, verdicts, strict=True):
            if v is None:
                continue
            judge_used += 1
            if v.equivalent:
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "status": "correct",
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })
            else:
                cells[cell_idx] = cells[cell_idx].model_copy(update={
                    "verdict_source": "llm_judge",
                    "judge_reason": v.reason,
                    "judge_model": v.model,
                })

    agg = _aggregate(cells, schema, reviewed)

    summary = ScoreResultSummary(
        n_docs=len(reviewed) + sum(1 for fn in predictions if fn not in reviewed),
        n_reviewed=agg.n_reviewed_graded,
        field_accuracy_macro=agg.field_accuracy_macro,
        macro_f1=None,  # M12.x: F1 demoted; new writes no longer carry it.
        doc_accuracy=agg.doc_accuracy,
        doc_accuracy_strict=agg.doc_accuracy_strict,
        per_field=agg.per_field,
        # M-compare 增量口径 —— 纯新增，旧 headline 语义一个没动。
        cell_accuracy_nonempty=agg.cell_accuracy_nonempty,
        required_cell_accuracy_nonempty=agg.required_cell_accuracy_nonempty,
        n_docs_perfect=agg.n_docs_perfect,
        n_docs_graded=agg.n_reviewed_graded,
        n_required_fields=agg.n_required_fields,
        errors=errors,
        ts=_now_ts(),
        schema_field_count=len(schema),
        judge_used=judge_used,
        judge_skipped_budget=judge_skipped_budget,
    )
    return summary, cells


async def _load_pred_and_reviewed(
    workspace: Path, project_id: str, pd_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    predictions: dict[str, list[dict[str, Any]]] = {}
    reviewed: dict[str, list[dict[str, Any]]] = {}
    if pd_path.exists():
        for p in sorted(pd_path.glob("*.json")):
            blob = json.loads(p.read_text())
            predictions[p.stem] = blob.get("entities", [])
    rd = reviewed_dir(workspace, project_id)
    if rd.exists():
        for p in sorted(rd.glob("*.json")):
            blob = json.loads(p.read_text())
            reviewed[p.stem] = blob.get("entities", [])
    return predictions, reviewed


def _write_cells_jsonl(path: Path, cells: list[CellVerdict]) -> None:
    lines = "\n".join(
        json.dumps(c.model_dump(mode="json"), ensure_ascii=False) for c in cells
    )
    path.write_text(lines + ("\n" if lines else ""), encoding="utf-8")


def _write_matrix_csv(
    path: Path, schema: list[SchemaField], cells: list[CellVerdict],
) -> None:
    path.write_text(cells_to_csv(schema, cells), encoding="utf-8")


def _write_meta(
    path: Path,
    workspace: Path,
    project_id: str,
    summary: ScoreResultSummary,
    experiment_id: Optional[str],
) -> None:
    # M12.x.d — the anchor (prompt_id/model_id + resolved labels) lives on
    # `summary`; copy it through so meta.json carries the same identity the
    # summary does. Eval listing surfaces (the chip in matrix list) read
    # from meta.json without loading the full summary.
    meta = {
        "prompt_id": summary.prompt_id,
        "prompt_label": summary.prompt_label,
        "model_id": summary.model_id,
        "extract_model": summary.extract_model,
        "experiment_id": experiment_id,
        "judge_used": summary.judge_used,
        "judge_skipped_budget": summary.judge_skipped_budget,
        "ts": summary.ts,
        "schema_field_count": summary.schema_field_count,
        "n_reviewed": summary.n_reviewed,
    }
    atomic_write_json(path, meta)


async def _resolve_run_anchor(
    workspace: Path, project_id: str, experiment_id: Optional[str],
) -> dict[str, Optional[str]]:
    """Resolve (prompt_id, prompt_label, model_id, extract_model) for this run.

    M14: anchor comes from the prediction blobs we're grading. If they carry
    `_run` (M14+), use it — that attributes metrics to the model that
    *produced* the blob, even after the project's `active_model_id` has been
    re-pointed between extract and score. Fall back to the legacy resolver
    (experiment meta / project.json active) only when blobs are pre-M14 or
    don't exist.
    """
    from app.workspace.paths import experiment_predictions_dir

    # ── M14 fast path: read the stamp off the first valid blob. We use the
    # first stamp we find since every prediction blob in the same dir was
    # written by the same (model, prompt) configuration. If any blob is
    # legacy / mid-write / unparseable, skip it and try the next one.
    pd_path = (
        experiment_predictions_dir(workspace, project_id, experiment_id)
        if experiment_id
        else predictions_draft_dir(workspace, project_id)
    )
    if pd_path.exists():
        for p in sorted(pd_path.glob("*.json")):
            try:
                blob = json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            run = blob.get("_run")
            if isinstance(run, dict):
                return {
                    "prompt_id": run.get("prompt_id"),
                    "prompt_label": run.get("prompt_label"),
                    "model_id": run.get("model_id"),
                    "extract_model": run.get("extract_model"),
                }

    # ── Legacy fallback: pre-M14 blobs (or empty dir). Read the experiment
    # meta or project.json active_* and resolve labels by reading the
    # referenced prompt / model. Same logic as before M14.
    pid: Optional[str] = None
    mid: Optional[str] = None
    if experiment_id:
        try:
            from app.tools.experiment import read_experiment
            ex = await read_experiment(workspace, project_id, experiment_id)
            pid, mid = ex.prompt_id, ex.model_id
        except Exception:
            pass
    if not pid or not mid:
        try:
            blob = json.loads(project_json_path(workspace, project_id).read_text())
            pid = pid or blob.get("active_prompt_id")
            mid = mid or blob.get("active_model_id")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    prompt_label: Optional[str] = None
    extract_model: Optional[str] = None
    if pid:
        try:
            from app.tools.prompt import read_prompt
            pv = await read_prompt(workspace, project_id, pid)
            prompt_label = pv.label
        except Exception:
            pass
    if mid:
        try:
            from app.tools.model import read_model
            mc = await read_model(workspace, project_id, mid)
            extract_model = mc.provider_model_id
        except Exception:
            pass
    return {
        "prompt_id": pid,
        "prompt_label": prompt_label,
        "model_id": mid,
        "extract_model": extract_model,
    }


async def run_eval(
    workspace: Path,
    project_id: str,
    *,
    use_llm_judge: bool = False,
    experiment_id: Optional[str] = None,
) -> ScoreResultSummary:
    from app.tools.schema import read_schema
    from app.workspace.paths import experiment_predictions_dir

    _validate_project_id(project_id)

    schema = await read_schema(workspace, project_id)

    if experiment_id:
        pd_path = experiment_predictions_dir(workspace, project_id, experiment_id)
    else:
        pd_path = predictions_draft_dir(workspace, project_id)

    predictions, reviewed = await _load_pred_and_reviewed(
        workspace, project_id, pd_path,
    )
    summary, cells = await score(
        workspace, project_id, schema, predictions, reviewed,
        use_llm_judge=use_llm_judge,
    )

    anchor = await _resolve_run_anchor(workspace, project_id, experiment_id)
    summary = summary.model_copy(update=anchor)

    async with project_lock(workspace, project_id):
        d = eval_dir(workspace, project_id, summary.ts)
        d.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            eval_summary_path(workspace, project_id, summary.ts),
            summary.model_dump(mode="json"),
        )
        _write_cells_jsonl(
            eval_cells_path(workspace, project_id, summary.ts), cells,
        )
        _write_matrix_csv(
            eval_matrix_path(workspace, project_id, summary.ts),
            schema, cells,
        )
        _write_meta(
            eval_meta_path(workspace, project_id, summary.ts),
            workspace, project_id, summary, experiment_id,
        )
    return summary
