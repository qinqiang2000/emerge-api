from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    CANCELLED = "cancelled"
    ERROR = "error"


class JobInfo(BaseModel):
    """In-memory and serialized status for a single job."""
    model_config = ConfigDict(extra="forbid")

    job_id: str
    project_id: str
    skill: str
    status: JobStatus
    params: dict[str, Any]
    created_at: str
    latest_turn: int = 0
    best_turn: int | None = None
    best_macro_f1: float | None = None
    error_code: str | None = None
    error_message_en: str | None = None


class JobEvent(BaseModel):
    """One JSONL line in jobs/{job_id}.jsonl. Loose-typed: each `type` carries
    its own payload keys. Consumers parse with type-specific logic."""
    model_config = ConfigDict(extra="allow")

    type: str
    ts: str
