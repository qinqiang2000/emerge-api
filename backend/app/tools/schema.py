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
from app.workspace.paths import doc_meta_path


class StructuralChangeError(Exception):
    """Raised when write_schema is called without allow_structural=True
    but the change adds, removes, or renames a field, or changes its type."""


async def read_schema(workspace: Path, project_id: str) -> list[SchemaField]:
    from app.tools.prompt import read_active_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    pv = await read_active_prompt(workspace, project_id)
    return pv.schema


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
    global_notes: str | None = None,
) -> None:
    """Thin wrapper over write_prompt — kept for one milestone for chat-tool backward compat.

    After M9.1, schema lives in prompts/{active}.json. The structural-change gate
    is preserved at this layer so the existing accept_candidate route and chat
    flow keep their safety net. New code should call write_prompt directly.

    The `reason` parameter is currently ignored (kept for signature compat).
    Pass `global_notes` to update it in the same atomic write; omit to preserve
    the current value.
    """
    from app.tools.prompt import read_active_prompt, write_prompt
    from app.workspace.migrate import migrate_project_if_needed

    await migrate_project_if_needed(workspace, project_id)
    old_pv = await read_active_prompt(workspace, project_id)
    if _is_structural_change(old_pv.schema, schema) and not allow_structural:
        raise StructuralChangeError(
            "structural change requires allow_structural=True (gated by agent)"
        )
    await write_prompt(
        workspace, project_id,
        prompt_id=None,
        schema=schema,
        global_notes=global_notes if global_notes is not None else old_pv.global_notes,
    )


_DERIVE_SYSTEM = """You are designing a JSON extraction schema for a document type.
Given sample documents and a user intent, propose a list of fields to extract.

Output rules:
- field names: letter-led identifiers `[A-Za-z][A-Za-z0-9_]*`. snake_case is the preferred default (e.g. `invoice_number`); camelCase is equally valid when it matches existing schemas or downstream systems (e.g. `docType`, `billToName`).
- prefer flat fields; nest only for natural arrays (line items, addresses)
- write a `description` for each field that says what to look for AND what format to output
- mark fields `required: true` only when they always appear

Use the provided tool to emit the schema."""


# Inline recursion (no $ref — Gemini's OpenAPI-3.0 dialect rejects it).
# Depth cap: top-level field can carry properties/items whose elements are
# scalar-only. This bounds proposer complexity; deeper nesting can be built
# manually in the editor.
_TYPE_ENUM = ["string", "number", "integer", "boolean", "object", "array"]
_FORMAT_ENUM = ["date", "date-time", "time"]


def _scalar_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["type", "description"],
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": _TYPE_ENUM},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "format": {"type": "string", "enum": _FORMAT_ENUM},
            "enum": {"type": "array", "items": {"type": "string"}},
        },
    }


def _nested_field_schema() -> dict[str, Any]:
    inner = _scalar_field_schema()
    return {
        "type": "object",
        "required": ["name", "type", "description"],
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": _TYPE_ENUM},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "format": {"type": "string", "enum": _FORMAT_ENUM},
            "enum": {"type": "array", "items": {"type": "string"}},
            "properties": {"type": "array", "items": inner},
            "items": inner,
        },
    }


_DERIVE_TOOL_SCHEMA = {
    "type": "object",
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": _nested_field_schema(),
        }
    },
}


def _scrub_proposer_field(node: Any) -> Any:
    """Strip stochastic毛刺 from proposer-LLM JSON before SchemaField validation.
    response_schema (OpenAPI 3.0) can't express "format only valid when type=string",
    so the proposer occasionally hangs format/enum/properties/items on the wrong type.
    Drop the mismatched keys per `SchemaField._shape` rules; nested items/properties
    are scrubbed recursively. Array items must be unnamed."""
    if not isinstance(node, dict):
        return node
    t = node.get("type")
    out = dict(node)
    if t != "string":
        out.pop("format", None)
        out.pop("enum", None)
    if t != "object":
        out.pop("properties", None)
    if t != "array":
        out.pop("items", None)
    props = out.get("properties")
    if isinstance(props, list):
        out["properties"] = [_scrub_proposer_field(c) for c in props]
    it = out.get("items")
    if isinstance(it, dict):
        scrubbed = _scrub_proposer_field(it)
        scrubbed.pop("name", None)
        out["items"] = scrubbed
    return out


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


async def _doc_to_block(workspace: Path, project_id: str, filename: str) -> ContentBlock:
    import json as _json
    meta = _json.loads(doc_meta_path(workspace, project_id, filename).read_text())
    data = await read_doc(workspace, project_id, filename)
    return _bytes_to_block(data, meta["ext"])


async def derive_schema(
    workspace: Path,
    project_id: str,
    *,
    sample_filenames: list[str],
    intent: str,
    provider: Provider,
    model_id: str,
) -> list[SchemaField]:
    user_blocks: list[ContentBlock] = [TextBlock(text=f"User intent: {intent}")]
    for fn in sample_filenames:
        user_blocks.append(await _doc_to_block(workspace, project_id, fn))

    result = await provider.extract(
        model_id=model_id,
        system_prompt=_DERIVE_SYSTEM,
        user_content=user_blocks,
        response_schema=_DERIVE_TOOL_SCHEMA,
    )
    raw_fields = result.raw_json.get("fields", [])
    out: list[SchemaField] = []
    for f in raw_fields:
        try:
            out.append(SchemaField(**_scrub_proposer_field(f)))
        except Exception:
            continue
    return out
