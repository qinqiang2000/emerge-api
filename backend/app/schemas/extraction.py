from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionOutput(BaseModel):
    """Wire format for extract_one tool output.

    Field name `evidence` serializes as `_evidence` on the wire (LLM contract).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    entities: list[dict[str, Any]]
    evidence: Optional[list[dict[str, Optional[int]]]] = Field(default=None, alias="_evidence")

    @model_validator(mode="after")
    def evidence_length_matches(self) -> "ExtractionOutput":
        if self.evidence is not None and len(self.evidence) != len(self.entities):
            raise ValueError("_evidence length must equal entities length")
        return self
