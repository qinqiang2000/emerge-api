from typing import Optional

from pydantic import BaseModel, ConfigDict


class FieldScore(BaseModel):
    """Per-field accuracy across all reviewed docs in this run."""
    model_config = ConfigDict(extra="forbid")

    field: str
    tp: int
    fp: int
    fn: int
    support: int
    precision: float
    recall: float
    f1: float
    accuracy: Optional[float] = None


class ScoreResultSummary(BaseModel):
    """Outcome of one /eval run."""
    model_config = ConfigDict(extra="forbid")

    n_docs: int
    n_reviewed: int
    macro_f1: float
    doc_accuracy: Optional[float] = None
    per_field: list[FieldScore]
    errors: list[str]
    ts: str
    schema_field_count: int
    judge_used: int = 0
    judge_skipped_budget: int = 0


# Back-compat alias: existing imports of ScoreResult keep working
ScoreResult = ScoreResultSummary
