from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExperimentEval(BaseModel):
    """Outcome of one run_experiment_eval call against the reviewed/ ground truth.

    M12.x — `score` now stores `field_accuracy_macro` (was `macro_f1` pre-M12.x);
    `per_field` values are per-field accuracy; `per_doc` values are per-doc
    field-accuracy-macro. Old experiments' `score` numbers stay literal —
    they remain F1-shaped snapshots — but new runs write accuracy.
    """
    model_config = ConfigDict(extra="forbid", frozen=False)

    ran_at: str
    score: float
    per_field: dict[str, float] = Field(default_factory=dict)
    per_doc: dict[str, float] = Field(default_factory=dict)
    run_id: str
    coverage: int


class Experiment(BaseModel):
    """A (prompt_id, model_id) reference pair plus optional eval + per-doc predictions.

    Disk: experiments/{experiment_id}/meta.json (this blob) +
          experiments/{experiment_id}/predictions/{filename}.json (per-doc payloads).
    """
    model_config = ConfigDict(extra="forbid", frozen=False)

    experiment_id: str
    label: str
    prompt_id: str
    model_id: str
    status: Literal["draft", "ran", "archived", "promoted"] = "draft"
    created_at: str
    promoted_at: Optional[str] = None
    notes: str = ""
    eval: Optional[ExperimentEval] = None
