from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


CellStatus = Literal["correct", "wrong", "missing", "spurious", "absent_both"]
VerdictSource = Literal["exact", "normalize", "llm_judge", "presence"]


class CellVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    entity_idx: int
    field: str
    status: CellStatus
    truth: Optional[str] = None
    pred: Optional[str] = None
    verdict_source: VerdictSource
    normalizer: Optional[str] = None
    judge_reason: Optional[str] = None
    judge_model: Optional[str] = None
