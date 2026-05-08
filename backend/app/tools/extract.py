from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.schema import _doc_to_block
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    predictions_draft_dir,
    project_json_path,
    schema_path,
)


_EXTRACT_SYSTEM = """You extract structured data from a document.

Output rules:
- top-level: array of objects (entities). One PDF may contain multiple entities (e.g. multiple receipts).
- snake_case English keys only.
- omit fields when uncertain (do NOT return null or empty strings as placeholders).
- emit `_evidence` parallel to `entities`: per-entity dict mapping field_name -> page integer (1-based).
  Use the page where you saw the value. For derived fields (sums, formatted dates) emit null.

Use the emit_extraction tool to return the result."""


def _build_response_schema(schema: list[SchemaField]) -> dict[str, Any]:
    """Convert SchemaField[] to JSON schema for tool input."""
    field_props: dict[str, Any] = {}
    required: list[str] = []
    for f in schema:
        field_props[f.name] = _field_jsonschema(f)
        if f.required:
            required.append(f.name)
    entity_schema: dict[str, Any] = {
        "type": "object",
        "properties": field_props,
    }
    if required:
        entity_schema["required"] = required

    # `_evidence` is intentionally omitted from the formal response_schema:
    # Gemini's OpenAPI-3.0 dialect rejects `additionalProperties` (which we'd need
    # to allow arbitrary field names as evidence keys), and listing each schema
    # field again as an explicit nullable integer doubles the schema for marginal
    # value at this layer. The system prompt still instructs the model to emit
    # `_evidence`; ExtractionOutput accepts it as Optional and validates length.
    return {
        "type": "object",
        "required": ["entities"],
        "properties": {
            "entities": {"type": "array", "items": entity_schema},
        },
    }


def _field_jsonschema(f: SchemaField) -> dict[str, Any]:
    base: dict[str, Any]
    if f.type == FieldType.STRING:
        base = {"type": "string"}
        if f.enum:
            base["enum"] = f.enum
    elif f.type == FieldType.NUMBER:
        base = {"type": "number"}
    elif f.type == FieldType.BOOLEAN:
        base = {"type": "boolean"}
    elif f.type == FieldType.DATE:
        base = {"type": "string", "format": "date"}
    elif f.type == FieldType.ARRAY_OBJECT:
        children = f.children or []
        base = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {c.name: _field_jsonschema(c) for c in children},
            },
        }
    else:
        base = {"type": "string"}
    base["description"] = f.description
    return base


def _build_field_instructions(schema: list[SchemaField]) -> str:
    lines = ["Per-field instructions:"]
    for i, f in enumerate(schema, start=1):
        suffix = ""
        if f.examples:
            suffix += f" Examples: {', '.join(f.examples)}."
        if f.enum:
            suffix += f" Allowed values: {', '.join(f.enum)}."
        lines.append(f"{i}. `{f.name}` ({f.type.value}): {f.description}{suffix}")
    return "\n".join(lines)


async def extract_one(
    workspace: Path,
    project_id: str,
    doc_id: str,
    *,
    provider: Provider,
    model_id: str | None = None,
) -> dict[str, Any]:
    schema = [SchemaField(**f) for f in json.loads(schema_path(workspace, project_id).read_text())]
    if not schema:
        raise ValueError("project has empty schema; nothing to extract")
    project = json.loads(project_json_path(workspace, project_id).read_text())
    mid = model_id or project["extract_model"]

    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        await _doc_to_block(workspace, project_id, doc_id),
    ]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=mid,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
    )

    output = ExtractionOutput(**result.raw_json)
    payload = output.model_dump(by_alias=True, exclude_none=True)

    async with project_lock(workspace, project_id):
        predictions_draft_dir(workspace, project_id).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            predictions_draft_dir(workspace, project_id) / f"{doc_id}.json",
            payload,
        )
    return payload


async def extract_batch(
    workspace: Path,
    project_id: str,
    doc_ids: list[str],
    *,
    provider: Provider,
    model_id: str | None = None,
    concurrency: int = 4,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    per_doc: dict[str, dict[str, Any]] = {}

    async def _run_one(did: str) -> None:
        async with sem:
            try:
                payload = await extract_one(workspace, project_id, did, provider=provider, model_id=model_id)
                per_doc[did] = {"ok": True, "entities": payload.get("entities", [])}
            except Exception as e:  # noqa: BLE001
                per_doc[did] = {"ok": False, "error": str(e)}

    await asyncio.gather(*(_run_one(d) for d in doc_ids))
    ok = sum(1 for v in per_doc.values() if v["ok"])
    err = sum(1 for v in per_doc.values() if not v["ok"])
    return {"ok_count": ok, "err_count": err, "per_doc": per_doc}
