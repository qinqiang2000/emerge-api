from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.provider.base import (
    ContentBlock,
    DocumentBlock,
    ImageBlock,
    Provider,
    TextBlock,
)
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import list_docs, read_doc
from app.workspace.jsonschema_transcode import transcode_to_schema_fields
from app.workspace.paths import chat_attachment_path, doc_meta_path


class StructuralChangeError(Exception):
    """Raised when write_schema is called without allow_structural=True
    but the change adds, removes, or renames a field, or changes its type."""


class SchemaImportError(ValueError):
    """Raised when an attempted schema import fails on parse / validation /
    extension. Carries `error_code` so HTTP / tool envelopes route the same
    way the rest of the lab API does (see `feedback_ai_native_api_symmetry`).

    Distinct from `StructuralChangeError` because the schema never reaches
    the structural gate — we fail upstream at YAML parsing or pydantic
    validation, before the writer is invoked.
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_message_en = message


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


_IMPORT_SCHEMA_EXTS = {"yml", "yaml", "json"}


def _format_field_error(idx: int, item: Any, exc: ValidationError) -> str:
    """Render one field's pydantic errors as a compact, agent-fixable line:
    `field[3] 'invoiceDate': items.description: Field required; ...`. Naming the
    field + every sub-error lets the agent fix them all before re-importing,
    instead of one error per round-trip."""
    label = item.get("name") if isinstance(item, dict) else None
    head = f"field[{idx}]" + (f" {label!r}" if label else "")
    parts = []
    for e in exc.errors():
        loc = ".".join(str(p) for p in e.get("loc", ()) if p != "__root__")
        msg = e.get("msg", "invalid")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return f"{head}: " + "; ".join(parts)


async def import_schema_from_yaml(
    workspace: Path,
    project_id: str,
    chat_id: str,
    filename: str,
    *,
    allow_structural: bool = True,
    as_new_variant: bool = False,
    new_label: str | None = None,
) -> dict[str, Any]:
    """Read a chat attachment (yml/yaml/json), parse as `list[SchemaField]`,
    and write it into the project as a prompt schema.

    The file must already live in `chats/<chat_id>/attachments/<filename>`
    (i.e. dropped/pasted into the composer and persisted by the staging /
    attach pipeline). Refuses upfront if the filename's extension isn't in
    `_IMPORT_SCHEMA_EXTS`.

    Two write targets:

    - `as_new_variant=False` (default): atomically **replace the active
      prompt's schema** via the existing `write_schema` writer + lock — same
      path a normal agent edit takes. `allow_structural=True` because import
      is inherently structural; pass `False` to surface the structural gate
      via `StructuralChangeError`. Returns `{ok, field_count, names}`.
    - `as_new_variant=True`: mint a **new prompt variant** (clone active for
      lineage, then overwrite its schema with the import) and leave the active
      prompt untouched — the user must `switch_active_prompt` to adopt it.
      `allow_structural` is irrelevant here (a fresh variant has no prior
      schema to gate against). `new_label` names the variant; defaults to
      `imported:<filename>`. Returns `{ok, as_new_variant, prompt_id, label,
      field_count, names}`.

    Surfaces parse / validation failures via `SchemaImportError` so the tool /
    HTTP envelope layers can render `{ok: false, error: {error_code,
    error_message_en}}`.
    """
    raw_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if raw_ext not in _IMPORT_SCHEMA_EXTS:
        raise SchemaImportError(
            "import_schema_unsupported_ext",
            f"unsupported extension for schema import: {filename!r}; "
            f"expected one of {sorted(_IMPORT_SCHEMA_EXTS)}",
        )

    path = chat_attachment_path(workspace, project_id, chat_id, filename)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(
            f"chat attachment not found: {project_id}/{chat_id}/{filename}"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SchemaImportError(
            "invalid_schema_yaml",
            f"failed to read attachment as UTF-8 text: {exc}",
        ) from exc

    # `yaml.safe_load` reads JSON natively (JSON is a strict YAML subset),
    # so one parser handles both `.yaml` and `.json`.
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SchemaImportError(
            "invalid_schema_yaml",
            f"yaml parse failed: {exc}",
        ) from exc

    # A non-list root is usually a foreign prompt bundle (Gemini/OpenAI
    # JSON-Schema). Try to transcode it into emerge's field-list shape rather
    # than bouncing the agent into a hand-conversion loop. On success we still
    # run the transcoded dicts through the same validation path below.
    converted_note: str | None = None
    if not isinstance(parsed, list):
        result = transcode_to_schema_fields(parsed)
        if result is None:
            raise SchemaImportError(
                "invalid_schema_yaml",
                "schema root must be a list of field dicts "
                f"(got {type(parsed).__name__}). This file is neither an emerge "
                "field list nor a recognizable JSON-Schema. emerge expects "
                "`[{name, type, description, ...}]`; if this is a Gemini/OpenAI "
                "prompt config, its field schema should sit under "
                "`prompt_template.json_schema` (or a top-level `json_schema` / "
                "`response_schema`) as an object with `properties`.",
            )
        parsed = result.fields
        converted_note = result.summary

    # Aggregate ALL field validation errors in one pass — fail-fast (one error
    # per re-import) is what turned a single bad import into a 21-turn loop.
    fields: list[SchemaField] = []
    field_errors: list[str] = []
    for idx, item in enumerate(parsed):
        try:
            fields.append(SchemaField.model_validate(item))
        except ValidationError as exc:
            field_errors.append(_format_field_error(idx, item, exc))
    if field_errors:
        raise SchemaImportError(
            "invalid_schema_yaml",
            "schema field validation failed:\n" + "\n".join(field_errors),
        )

    if as_new_variant:
        from app.tools.prompt import (
            create_prompt,
            read_active_prompt,
            write_prompt,
        )

        active = await read_active_prompt(workspace, project_id)
        label = new_label or f"imported:{filename}"
        # create_prompt clones the active variant (records derived_from lineage);
        # we then overwrite its schema with the import, keeping the cloned
        # global_notes so the new variant inherits project-level guidance.
        new_id = await create_prompt(workspace, project_id, label=label)
        await write_prompt(
            workspace,
            project_id,
            prompt_id=new_id,
            schema=fields,
            global_notes=active.global_notes,
        )
        out = {
            "ok": True,
            "as_new_variant": True,
            "prompt_id": new_id,
            "label": label,
            "field_count": len(fields),
            "names": [f.name for f in fields if f.name],
        }
        if converted_note:
            out["converted_from"] = "json-schema"
            out["notes"] = converted_note
        return out

    await write_schema(
        workspace,
        project_id,
        fields,
        reason=f"import_schema_from_yaml({filename})",
        allow_structural=allow_structural,
    )
    out = {
        "ok": True,
        "field_count": len(fields),
        "names": [f.name for f in fields if f.name],
    }
    if converted_note:
        out["converted_from"] = "json-schema"
        out["notes"] = converted_note
    return out
