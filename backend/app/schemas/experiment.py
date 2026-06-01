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
    # M14-style audit link to the metrics/eval_<ts>/ dir that produced this
    # score. New field — Optional for backwards-compat with pre-T1 meta.json.
    # Bench backend uses this to route experiment row click → EvalMatrixModal.
    summary_ts: Optional[str] = None


class Experiment(BaseModel):
    """A (prompt_id, model_id) reference pair plus optional eval + per-doc predictions.

    Disk: experiments/{experiment_id}/meta.json (this blob) +
          experiments/{experiment_id}/predictions/{filename}.json (per-doc payloads).
    """
    model_config = ConfigDict(extra="forbid", frozen=False)

    experiment_id: str
    label: str
    prompt_id: str
    # Content version of `prompt_id` at creation time (PromptVariant.version).
    # Frozen — pins which prompt snapshot this experiment's predictions came
    # from, so re-running after a tune mints a NEW experiment instead of
    # silently overwriting an older version's results under the same tab.
    # None for pre-versioning experiments.
    prompt_version: Optional[int] = None
    model_id: str
    status: Literal["draft", "ran", "archived", "promoted"] = "draft"
    created_at: str
    promoted_at: Optional[str] = None
    notes: str = ""
    eval: Optional[ExperimentEval] = None
