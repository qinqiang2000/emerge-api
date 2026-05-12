from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.schema_field import SchemaField


class PromptVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    prompt_id: str
    label: str
    schema: list[SchemaField]
    global_notes: str = ""
    derived_from: Optional[str] = None
    created_at: str
    updated_at: str
