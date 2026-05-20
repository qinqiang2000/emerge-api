from __future__ import annotations

from typing import Any, Literal

from app.schemas.schema_field import SchemaField


AbsentPolicy = Literal["lenient", "strict"]
DEFAULT_PROJECT_POLICY: AbsentPolicy = "lenient"
LENIENT_ABSENT_LITERALS = frozenset({"", "n/a", "none", "null"})


def resolve_policy(
    field: SchemaField,
    project_default: AbsentPolicy = DEFAULT_PROJECT_POLICY,
) -> AbsentPolicy:
    return field.absent_policy or project_default


def is_absent(value: Any, policy: AbsentPolicy) -> bool:
    if value is None:
        return True
    if policy == "strict":
        return False
    if isinstance(value, str):
        return value.strip().lower() in LENIENT_ABSENT_LITERALS
    return False
