from __future__ import annotations

from typing import Any

from app.schemas.schema_field import SchemaField


def contract_diff(
    prev: list[SchemaField],
    candidate: list[SchemaField],
) -> dict[str, Any]:
    """Top-level backward-compatibility diff for publish gating."""
    prev_by_name = {f.name: f for f in prev}
    cand_by_name = {f.name: f for f in candidate}

    added = sorted(set(cand_by_name) - set(prev_by_name))
    removed = sorted(set(prev_by_name) - set(cand_by_name))

    type_changed: list[dict[str, str]] = []
    enum_narrowed: list[dict[str, Any]] = []
    for name in sorted(set(prev_by_name) & set(cand_by_name)):
        before = prev_by_name[name]
        after = cand_by_name[name]
        if before.type != after.type:
            type_changed.append({
                "name": name,
                "prev_type": before.type.value,
                "candidate_type": after.type.value,
            })
            continue

        prev_enum = before.enum
        cand_enum = after.enum
        if prev_enum is None and cand_enum is not None:
            enum_narrowed.append({
                "name": name,
                "prev_enum": None,
                "candidate_enum": list(cand_enum),
            })
        elif prev_enum is not None and cand_enum is not None:
            if not set(prev_enum).issubset(set(cand_enum)):
                enum_narrowed.append({
                    "name": name,
                    "prev_enum": list(prev_enum),
                    "candidate_enum": list(cand_enum),
                })

    is_breaking = bool(removed or type_changed or enum_narrowed)
    return {
        "added": added,
        "removed": removed,
        "type_changed": type_changed,
        "enum_narrowed": enum_narrowed,
        "is_breaking": is_breaking,
    }
