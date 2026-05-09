from __future__ import annotations

from typing import Any

from app.provider.base import Provider, TextBlock
from app.schemas.schema_field import SchemaField


PROPOSER_SYSTEM_PROMPT = """You are improving a JSON extraction schema for a document-extraction API.

Given the current schema, ground-truth reviewed examples, the latest model
predictions, the per-field score, and user inline notes, propose a revised
schema. The ONLY change you may make is rewording each field's `description`
(adding rules, sharpening format guidance, encoding edge cases the user
flagged in notes).

Hard constraints:
- DO NOT add fields.
- DO NOT remove fields.
- DO NOT rename fields.
- DO NOT retype fields.
- Keep the field order identical.
- For each field, return `name`, `type`, and `description` (and the original
  `required`/`enum`/`examples`/`children` if present), but only `description`
  may differ from the input.

Treat the user's inline `_notes` as high-priority hints - they are direct
human feedback on what's wrong. Sample errors show concrete reviewed-vs-
prediction disagreements per doc.

Output via the propose_schema tool. Include a short `rationale` explaining
which descriptions you changed and why."""


PROPOSER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["fields", "rationale"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["string", "number", "boolean", "date", "array<object>"],
                    },
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}


def build_proposer_user_text(
    *,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> str:
    lines: list[str] = []

    lines.append("=== current schema ===")
    for f in schema:
        lines.append(f"- {f.name} ({f.type.value}): {f.description}")

    lines.append("")
    lines.append("=== per-field score ===")
    if not per_field:
        lines.append("(no graded fields)")
    else:
        for fs in per_field:
            lines.append(
                f"- {fs['field']}: f1={fs['f1']:.2f} tp={fs['tp']} fp={fs['fp']} fn={fs['fn']}"
            )

    lines.append("")
    lines.append("=== sample errors (reviewed vs prediction) ===")
    any_err = False
    for doc_id, rev_entities in reviewed.items():
        rev = rev_entities[0] if rev_entities else {}
        pred_entities = predictions.get(doc_id, [])
        pred = pred_entities[0] if pred_entities else {}
        for f in schema:
            r = rev.get(f.name)
            p = pred.get(f.name)
            if r is not None and r != p:
                any_err = True
                lines.append(f"- {doc_id}.{f.name}: reviewed={r!r} predicted={p!r}")
    if not any_err:
        lines.append("(no field-level errors)")

    lines.append("")
    lines.append("=== user notes (high-priority hints) ===")
    flat: list[str] = []
    for doc_id, per_field_notes in notes.items():
        for fname, note in per_field_notes.items():
            flat.append(f"- {doc_id}.{fname}: {note}")
    if not flat:
        lines.append("(none)")
    else:
        lines.extend(flat)

    return "\n".join(lines)


class ProposerStructuralChangeError(Exception):
    """Raised when the proposer LLM tried to add/remove/rename/retype a field.
    The autoresearch loop treats this as a non-improving turn and continues."""


async def propose_schema(
    *,
    provider: Provider,
    model_id: str,
    schema: list[SchemaField],
    reviewed: dict[str, list[dict[str, Any]]],
    predictions: dict[str, list[dict[str, Any]]],
    per_field: list[dict[str, Any]],
    notes: dict[str, dict[str, str]],
) -> tuple[list[SchemaField], str]:
    """One proposer LLM call. Returns (revised schema, rationale).

    Raises ProposerStructuralChangeError if the proposer attempts to add /
    remove / rename / retype any field - only `description` text may change.
    """
    user_text = build_proposer_user_text(
        schema=schema, reviewed=reviewed, predictions=predictions,
        per_field=per_field, notes=notes,
    )
    result = await provider.extract(
        model_id=model_id,
        system_prompt=PROPOSER_SYSTEM_PROMPT,
        user_content=[TextBlock(text=user_text)],
        response_schema=PROPOSER_RESPONSE_SCHEMA,
        params={"temperature": 0.2},
    )
    blob = result.raw_json
    rationale = str(blob.get("rationale", ""))
    raw_fields: list[dict[str, Any]] = list(blob.get("fields") or [])

    if len(raw_fields) != len(schema):
        raise ProposerStructuralChangeError(
            f"proposer returned {len(raw_fields)} fields; expected {len(schema)}"
        )
    proposed: list[SchemaField] = []
    for old, new in zip(schema, raw_fields):
        if new.get("name") != old.name:
            raise ProposerStructuralChangeError(
                f"proposer changed field name {old.name!r} -> {new.get('name')!r}"
            )
        if new.get("type") != old.type.value:
            raise ProposerStructuralChangeError(
                f"proposer changed type for {old.name!r} "
                f"{old.type.value!r} -> {new.get('type')!r}"
            )
        # Carry forward old metadata that the proposer doesn't touch.
        merged = old.model_dump(mode="json")
        merged["description"] = str(new.get("description", old.description))
        proposed.append(SchemaField(**merged))

    return proposed, rationale
