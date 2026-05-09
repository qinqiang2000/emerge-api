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


class ScoreResult(BaseModel):
    """Outcome of one /eval run."""
    model_config = ConfigDict(extra="forbid")

    n_docs: int
    n_reviewed: int
    macro_f1: float
    per_field: list[FieldScore]
    errors: list[str]
    ts: str
    schema_field_count: int
