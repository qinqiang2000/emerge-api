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
    """
    model_config = ConfigDict(extra="forbid")

    n_docs: int
    n_reviewed: int
    field_accuracy_macro: Optional[float] = None
    macro_f1: Optional[float] = None
    doc_accuracy: Optional[float] = None
    per_field: list[FieldScore]
    errors: list[str]
    ts: str
    schema_field_count: int
    judge_used: int = 0
    judge_skipped_budget: int = 0


# Back-compat alias: existing imports of ScoreResult keep working
ScoreResult = ScoreResultSummary
