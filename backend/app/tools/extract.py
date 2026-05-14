from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from app.provider.base import ContentBlock, Provider, TextBlock
from app.schemas.extraction import ExtractionOutput
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.schema import _doc_to_block
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import (
    prediction_draft_path,
    predictions_draft_dir,
)


_EXTRACT_SYSTEM = """You extract structured data from a document.

Output rules:
- top-level: array of objects (entities). One PDF may contain multiple entities (e.g. multiple receipts).
- snake_case English keys only.
- ALWAYS include every field declared in the schema for each entity. Use null when the value is absent from the document or you are uncertain. Do NOT omit keys.
- emit `_evidence` parallel to `entities`: per-entity dict mapping field_name -> page integer (1-based).
  Use the page where you saw the value. For derived fields (sums, formatted dates) emit null.

Use the emit_extraction tool to return the result."""


def _build_response_schema(schema: list[SchemaField]) -> dict[str, Any]:
    """Convert SchemaField[] to JSON schema for tool input.

    Every schema field is marked `required` and `nullable:true` so that Gemini
    always emits the key (with null when absent). The user-facing schema
    definition == prediction key set; SchemaField.required only documents
    intent and is not enforced at this layer.
    """
    entity_schema: dict[str, Any] = {
        "type": "object",
        "properties": {f.name: _field_jsonschema(f) for f in schema},
        "required": [f.name for f in schema],
    }

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
                "required": [c.name for c in children],
            },
        }
    else:
        base = {"type": "string"}
    base["description"] = f.description
    base["nullable"] = True
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
    filename: str,
    *,
    provider: Provider,
    model_id: str | None = None,
) -> dict[str, Any]:
    from app.tools.model import read_active_model
    from app.tools.schema import read_schema
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    schema = await read_schema(workspace, project_id)
    if not schema:
        raise ValueError("project has empty schema; nothing to extract")
    if model_id is None:
        mc = await read_active_model(workspace, project_id)
        mid = mc.provider_model_id
    else:
        mid = model_id

    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        await _doc_to_block(workspace, project_id, filename),
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
            prediction_draft_path(workspace, project_id, filename),
            payload,
        )
    return payload


async def extract_one_with_schema(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Like extract_one but uses an in-memory schema (does NOT read schema.json
    or write predictions/_draft/). Used by the autoresearch loop to grade
    candidate schemas without mutating disk state."""
    if not schema:
        raise ValueError("schema must be non-empty")

    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        await _doc_to_block(workspace, project_id, filename),
    ]
    response_schema = _build_response_schema(schema)
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=response_schema,
        params=params if params is not None else {"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")


async def extract_bytes_with_schema(
    *,
    content: bytes,
    filename: str,
    schema: list[SchemaField],
    provider: Provider,
    model_id: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract from raw multipart bytes without writing the upload to workspace."""
    if not schema:
        raise ValueError("schema must be non-empty")
    from app.tools.schema import _bytes_to_block

    ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
    block = _bytes_to_block(content, ext)
    user_blocks: list[ContentBlock] = [
        TextBlock(text=_build_field_instructions(schema)),
        block,
    ]
    result = await provider.extract(
        model_id=model_id,
        system_prompt=_EXTRACT_SYSTEM,
        user_content=user_blocks,
        response_schema=_build_response_schema(schema),
        params=params or {"temperature": 0.0},
    )
    parsed = ExtractionOutput(**result.raw_json)
    return parsed.model_dump(by_alias=True, exclude_none=True, mode="json")


async def extract_batch(
    workspace: Path,
    project_id: str,
    filenames: list[str],
    *,
    provider: Provider,
    model_id: str | None = None,
    concurrency: int = 4,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    per_doc: dict[str, dict[str, Any]] = {}

    async def _run_one(fn: str) -> None:
        async with sem:
            try:
                payload = await extract_one(workspace, project_id, fn, provider=provider, model_id=model_id)
                per_doc[fn] = {"ok": True, "entities": payload.get("entities", [])}
            except Exception as e:  # noqa: BLE001
                per_doc[fn] = {"ok": False, "error": str(e)}

    await asyncio.gather(*(_run_one(f) for f in filenames))
    ok = sum(1 for v in per_doc.values() if v["ok"])
    err = sum(1 for v in per_doc.values() if not v["ok"])
    return {"ok_count": ok, "err_count": err, "per_doc": per_doc}
