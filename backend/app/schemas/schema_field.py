from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class StringFormat(str, Enum):
    DATE = "date"
    DATE_TIME = "date-time"
    TIME = "time"


def _normalize_legacy(data: Any) -> Any:
    """Read-side upgrade: {type:"date"} → string+format=date, {type:"array<object>", children:[…]} → array+items.object.properties.
    Idempotent — already-new shapes pass through untouched."""
    if not isinstance(data, dict):
        return data
    t = data.get("type")
    if t == "date":
        data = {**data, "type": "string", "format": "date"}
        data.pop("children", None)
    elif t == "array<object>":
        kids = data.get("children") or []
        items = {
            "type": "object",
            "description": data.get("description", ""),
            "properties": kids,
            "name": None,
        }
        new = {k: v for k, v in data.items() if k not in ("children", "items")}
        new["type"] = "array"
        new["items"] = items
        data = new
    elif "children" in data:
        # Legacy ARRAY_OBJECT siblings sometimes carried children=null on
        # non-array fields. Drop the dead key so extra="forbid" doesn't reject.
        data = {k: v for k, v in data.items() if k != "children"}
    return data


class SchemaField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)

    name: Optional[str] = None
    type: FieldType
    description: str
    required: bool = False
    format: Optional[StringFormat] = None
    enum: Optional[list[str]] = None
    properties: Optional[list["SchemaField"]] = None
    items: Optional["SchemaField"] = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = _normalize_legacy(data)
            kids = data.get("properties")
            if isinstance(kids, list):
                data = {**data, "properties": [_normalize_legacy(c) for c in kids]}
            it = data.get("items")
            if isinstance(it, dict):
                data = {**data, "items": _normalize_legacy(it)}
        return data

    @field_validator("name")
    @classmethod
    def name_identifier(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _NAME_RE.match(v):
            raise ValueError(
                f"field name must be a letter-led identifier ([A-Za-z][A-Za-z0-9_]*): {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _shape(self) -> "SchemaField":
        if self.format is not None and self.type != FieldType.STRING:
            raise ValueError("`format` is only valid when type=string")
        if self.enum is not None and self.type != FieldType.STRING:
            raise ValueError("`enum` is only valid when type=string")
        if self.type == FieldType.OBJECT:
            if not self.properties:
                raise ValueError("type=object requires non-empty `properties`")
            for child in self.properties:
                if not child.name:
                    raise ValueError("object property must have a name")
        else:
            if self.properties is not None:
                raise ValueError("`properties` only valid when type=object")
        if self.type == FieldType.ARRAY:
            if self.items is None:
                raise ValueError("type=array requires `items`")
            if self.items.name is not None:
                raise ValueError("array item shape must not have a name")
        else:
            if self.items is not None:
                raise ValueError("`items` only valid when type=array")
        return self


SchemaField.model_rebuild()


def validate_top_level(fields: list[SchemaField]) -> list[SchemaField]:
    """Enforce that top-level fields (and object.properties entries, recursively
    via the model validator) have names. Use at API/tool boundaries where a list
    of named fields is required."""
    for f in fields:
        if not f.name:
            raise ValueError("top-level schema field must have a name")
    return fields
