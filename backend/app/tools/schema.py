from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    TextBlock,
)
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import list_docs, read_doc
from app.workspace.atomic import atomic_write_json
from app.workspace.lock import project_lock
from app.workspace.paths import doc_meta_path, schema_path


class StructuralChangeError(Exception):
    """Raised when write_schema is called without allow_structural=True
    but the change adds, removes, or renames a field, or changes its type."""


async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    raw = json.loads(schema_path(workspace, project_id).read_text())
    return [SchemaField(**f) for f in raw]


def _is_structural_change(old: list[SchemaField], new: list[SchemaField]) -> bool:
    old_map = {f.name: f.type for f in old}
    new_map = {f.name: f.type for f in new}
    if set(old_map.keys()) != set(new_map.keys()):
        return True
    for name in old_map:
        if old_map[name] != new_map[name]:
            return True
    return False


async def write_schema(
    workspace: Path,
    project_id: str,
    schema: list[SchemaField],
    *,
    reason: str,
    allow_structural: bool = False,
) -> None:
    async with project_lock(workspace, project_id):
        sp = schema_path(workspace, project_id)
        if sp.exists():
            old = [SchemaField(**f) for f in json.loads(sp.read_text())]
            if _is_structural_change(old, schema) and not allow_structural:
                raise StructuralChangeError(
                    "structural change requires allow_structural=True (gated by agent)"
                )
        payload = [f.model_dump(mode="json") for f in schema]
        atomic_write_json(sp, payload)


_DERIVE_SYSTEM = """You are designing a JSON extraction schema for a document type.
Given sample documents and a user intent, propose a list of fields to extract.

Output rules:
- snake_case English keys only
- prefer flat fields; nest only for natural arrays (line items, addresses)
- write a `description` for each field that says what to look for AND what format to output
- mark fields `required: true` only when they always appear

Use the provided tool to emit the schema."""


_DERIVE_TOOL_SCHEMA = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "description"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["string", "number", "boolean", "date", "array<object>"]},
                    "description": {"type": "string"},
                    "required": {"type": "boolean"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "enum": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


_SUPPORTED_EXTS = {"pdf", "png", "jpg", "jpeg"}


def _bytes_to_block(data: bytes, ext: str) -> ContentBlock:
    ext = ext.lower().lstrip(".")
    if ext not in _SUPPORTED_EXTS:
        raise ValueError(f"unsupported file extension: {ext!r}")
    b64 = base64.b64encode(data).decode("ascii")
    if ext == "pdf":
        return DocumentBlock(media_type="application/pdf", data_b64=b64)
    media_type = "image/png" if ext == "png" else "image/jpeg"
    return ImageBlock(media_type=media_type, data_b64=b64)


async def _doc_to_block(workspace: Path, project_id: str, doc_id: str) -> ContentBlock:
    import json as _json
    meta = _json.loads(doc_meta_path(workspace, project_id, doc_id).read_text())
    data = await read_doc(workspace, project_id, doc_id)
    return _bytes_to_block(data, meta["ext"])


async def derive_schema(
    workspace: Path,
    project_id: str,
    *,
    sample_doc_ids: list[str],
    intent: str,
    provider: Provider,
    model_id: str = "claude-sonnet-4-6",
) -> list[SchemaField]:
    user_blocks: list[ContentBlock] = [TextBlock(text=f"User intent: {intent}")]
    for did in sample_doc_ids:
        user_blocks.append(await _doc_to_block(workspace, project_id, did))

    result = await provider.extract(
        model_id=model_id,
        system_prompt=_DERIVE_SYSTEM,
        user_content=user_blocks,
        response_schema=_DERIVE_TOOL_SCHEMA,
    )
    raw_fields = result.raw_json.get("fields", [])
    out: list[SchemaField] = []
    for f in raw_fields:
        out.append(SchemaField(**f))
    return out
