from typing import Optional

from pydantic import BaseModel, ConfigDict


class FieldScore(BaseModel):
    """Per-field score across all reviewed docs in this run.

    M12.x — accuracy-first: `accuracy = (correct + absent_both) / total`
    is the headline number. F1/precision/recall are demoted to optional —
    legacy summaries on disk still validate, but new writes emit `None`
    for the F1 family so nobody reads stale numbers as authoritative.

    `not_applicable=True` when `total==0` (schema has the field but no
    reviewed entity ever exposes it — exclude from macro). `n_absent_both`
    surfaces how many cells were "both sides agreed absent" — useful UI
    hint for rarely-present fields.

    M-compare — 「GT 有值格」一档（见 `app/eval/score.py::_aggregate`）：
    `n_wrong / n_missing / n_spurious` 把五档补齐，`accuracy_nonempty` 是
    `correct/(correct+wrong+missing)`，`None` 表示这个字段没有可判的有值格
    （**不是** 0% —— 别把它渲染成 0）。要拿有值格的原始计数时：

        分子 = correct - n_absent_both     # `correct` 里混了 absent_both
        分母 = 分子 + n_wrong + n_missing  # spurious 不进分母

    全部带默认值 —— 磁盘上的历史 `metrics/eval_*/summary.json` 没有这些键，
    `extra="forbid"` 只挡多余键，缺键靠默认值兜住。
    """
    model_config = ConfigDict(extra="forbid")

    field: str

    # M12.x accuracy-first fields (default to 0/False to remain readable on
    # legacy summaries that don't carry them).
    accuracy: Optional[float] = None
    correct: int = 0
    total: int = 0
    n_absent_both: int = 0
    not_applicable: bool = False

    # M-compare — 五档分计数 + GT 有值格准确率 + ★重要字段标记。
    n_wrong: int = 0
    n_missing: int = 0
    n_spurious: int = 0
    accuracy_nonempty: Optional[float] = None
    required: bool = False

    # Demoted F1 family — readable on legacy disk JSON, `None` on new writes.
    tp: Optional[int] = None
    fp: Optional[int] = None
    fn: Optional[int] = None
    support: Optional[int] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
    f1: Optional[float] = None


class ScoreResultSummary(BaseModel):
    """Outcome of one /eval run.

    M12.x: `field_accuracy_macro` is the new headline. `macro_f1` is kept
    as `Optional[float]` so legacy `metrics/eval_*.json` blobs on disk still
    parse; new writes set it to `None`.

    M12.x.c: `doc_accuracy` semantics shifted from "strict all-cells-correct"
    to "smooth mean of per-doc accuracy" on new writes. Old summary.json
    blobs that carried the strict value still parse (the field is Optional)
    — the disambiguator is `doc_accuracy_strict`: when present, the
    sibling `doc_accuracy` is the new smooth definition.

    M-compare: `cell_accuracy_nonempty` 系列是**格级微平均**的 GT 有值格
    口径（对比报告的头条），`field_accuracy_macro` 仍是字段级宏平均且语义
    未动 —— publish gate / autoresearch 还压在后者身上。新键一律带默认值，
    历史 summary.json 照常 parse。
    """
    model_config = ConfigDict(extra="forbid")

    n_docs: int
    n_reviewed: int
    field_accuracy_macro: Optional[float] = None
    macro_f1: Optional[float] = None
    doc_accuracy: Optional[float] = None
    # M12.x.c — legacy strict view; Optional so old summaries parse.
    doc_accuracy_strict: Optional[float] = None
    # M-compare — GT 有值格微平均（correct/(correct+wrong+missing)，剔掉
    # 两边都空的送分格）。`None` = 没有可判的有值格，不是 0%。
    cell_accuracy_nonempty: Optional[float] = None
    # 同上，但只算 `SchemaField.required=True` 的字段（★重要字段那一行）。
    required_cell_accuracy_nonempty: Optional[float] = None
    # 「整篇零错」的 n/N —— 比 `doc_accuracy_strict` 那个比值更适合给人看。
    n_docs_perfect: Optional[int] = None
    n_docs_graded: Optional[int] = None
    n_required_fields: Optional[int] = None
    per_field: list[FieldScore]
    errors: list[str]
    ts: str
    schema_field_count: int
    judge_used: int = 0
    judge_skipped_budget: int = 0
    # M12.x.d — (prompt, model) anchor so the chat headline narrates which
    # configuration produced these metrics. Resolved labels (`prompt_label`
    # = user-facing variant name, `extract_model` = provider_model_id like
    # `gemini-2.5-flash`) are filled by `run_eval`; Optional so legacy disk
    # summaries that pre-date these fields still validate.
    prompt_id: Optional[str] = None
    prompt_label: Optional[str] = None
    model_id: Optional[str] = None
    extract_model: Optional[str] = None


# Back-compat alias: existing imports of ScoreResult keep working
ScoreResult = ScoreResultSummary
