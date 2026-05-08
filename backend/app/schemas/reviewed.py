from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ReviewedSource(str, Enum):
    MANUAL = "manual"
    FEEDBACK = "feedback"


class Reviewed(BaseModel):
    """Ground-truth reviewed extraction for a doc.

    On the wire: `notes` is serialized as `_notes`. The leading underscore
    keeps it visually grouped with `_evidence` in the JSON file but the
    Python attribute uses a regular name.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    source: ReviewedSource = ReviewedSource.MANUAL
    notes: Optional[dict[str, str]] = Field(default=None, alias="_notes")
