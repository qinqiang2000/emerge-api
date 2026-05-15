from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    ARRAY_OBJECT = "array<object>"


class SchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    name: str
    type: FieldType
    description: str
    required: bool = False
    enum: Optional[list[str]] = None
    children: Optional[list["SchemaField"]] = None

    @field_validator("name")
    @classmethod
    def name_snake_case(cls, v: str) -> str:
        if not _SNAKE_CASE.match(v):
            raise ValueError(f"field name must be snake_case: {v!r}")
        return v

    @model_validator(mode="after")
    def array_object_needs_children(self) -> "SchemaField":
        if self.type == FieldType.ARRAY_OBJECT and not self.children:
            raise ValueError("type=array<object> requires non-empty children")
        return self


SchemaField.model_rebuild()
