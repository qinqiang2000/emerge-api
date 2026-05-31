"""JSON-Schema → SchemaField transcoder (the chinhin.yaml de-spiral).

Covers the pure transcoder plus its wiring into `import_schema_from_yaml`:
- Gemini prompt-config bundle (array root + anyOf variant branches) → flat
  field list that validates clean
- nullable anyOf collapse, UPPERCASE type lowercasing, required-array folding
- unrecognizable dict → teaching error (not a silent guess)
- aggregated validation: a hand-edited file with several bad fields reports
  ALL of them in one error, not one-per-re-import
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.schema_field import SchemaField
from app.tools.projects import create_project
from app.tools.prompt import read_active_prompt
from app.tools.schema import SchemaImportError, import_schema_from_yaml
from app.workspace.jsonschema_transcode import transcode_to_schema_fields
from app.workspace.paths import chat_attachments_dir


# A miniature of the chinhin.yaml shape: Gemini config, array root, two anyOf
# object variants, nullable anyOf fields, UPPERCASE types, required arrays.
_GEMINI_BUNDLE = {
    "id": "7_6",
    "remark": "gemini json schema, uses anyOf",
    "prompt_template": {
        "prompt_format": "extract the bills",
        "json_schema": {
            "title": "bills",
            "type": "ARRAY",
            "items": {
                "anyOf": [
                    {
                        "type": "OBJECT",
                        "required": ["docType", "page"],
                        "properties": {
                            "docType": {
                                "type": "STRING",
                                "description": "kind",
                                "enum": ["invoice", "receipt"],
                            },
                            "page": {
                                "type": "ARRAY",
                                "description": "pages",
                                "items": {"type": "NUMBER", "description": "p"},
                            },
                            "invoiceDate": {
                                "anyOf": [
                                    {"type": "STRING", "format": "date"},
                                    {"type": "null"},
                                ],
                                "description": "doc date",
                            },
                            "lines": {
                                "type": "ARRAY",
                                "description": "line items",
                                "items": {
                                    "type": "OBJECT",
                                    "required": ["name"],
                                    "properties": {
                                        "name": {"type": "STRING", "description": "n"},
                                        "amount": {"type": "NUMBER", "description": "a"},
                                    },
                                },
                            },
                        },
                    },
                    {
                        "type": "OBJECT",
                        "required": ["docType"],
                        "properties": {
                            "docType": {"type": "STRING", "description": "kind"},
                            "receiptOnlyField": {"type": "STRING", "description": "r"},
                        },
                    },
                ]
            },
        },
    },
}


def test_transcode_gemini_bundle_to_valid_fields() -> None:
    r = transcode_to_schema_fields(_GEMINI_BUNDLE)
    assert r is not None
    names = [f["name"] for f in r.fields]
    # Union of both variant branches; docType deduped.
    assert names.count("docType") == 1
    assert "receiptOnlyField" in names  # merged from the second branch
    assert "merged 2 variant branches" in r.summary
    assert "unwrapped array root" in r.summary
    # Every transcoded field validates through the real model.
    for f in r.fields:
        SchemaField.model_validate(f)


def test_transcode_resolves_nullable_anyof_and_lowercases_types() -> None:
    r = transcode_to_schema_fields(_GEMINI_BUNDLE)
    by = {f["name"]: f for f in r.fields}
    # nullable anyOf → string+format=date, null branch dropped, desc carried down.
    assert by["invoiceDate"]["type"] == "string"
    assert by["invoiceDate"]["format"] == "date"
    assert by["invoiceDate"]["description"] == "doc date"
    # UPPERCASE NUMBER/ARRAY/OBJECT all lowercased.
    assert by["page"]["type"] == "array"
    assert by["page"]["items"]["type"] == "number"
    assert by["lines"]["items"]["type"] == "object"
    # required array folded into per-field booleans.
    assert by["docType"]["required"] is True
    assert by["page"]["required"] is True
    assert by["invoiceDate"].get("required", False) is False
    # nested object required folded too.
    line_props = {p["name"]: p for p in by["lines"]["items"]["properties"]}
    assert line_props["name"]["required"] is True
    assert line_props["amount"].get("required", False) is False


def test_transcode_raw_json_schema_root() -> None:
    schema = {
        "type": "object",
        "required": ["a"],
        "properties": {
            "a": {"type": "string", "description": "x"},
            "b": {"type": "integer", "description": "y"},
        },
    }
    r = transcode_to_schema_fields(schema)
    assert r is not None
    assert [f["name"] for f in r.fields] == ["a", "b"]
    assert "raw JSON-Schema root" in r.summary


def test_transcode_returns_none_for_non_schema_dict() -> None:
    # A plain config dict that isn't a JSON-Schema at all.
    assert transcode_to_schema_fields({"foo": 1, "bar": 2}) is None
    assert transcode_to_schema_fields(["a", "b"]) is None


# ── wiring into import_schema_from_yaml ─────────────────────────────────────


def _seed(workspace: Path, slug: str, chat_id: str, filename: str, body: bytes) -> None:
    d = chat_attachments_dir(workspace, slug, chat_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(body)


_GEMINI_YAML = """\
id: '7_6'
prompt_template:
  json_schema:
    type: ARRAY
    items:
      type: OBJECT
      required: [docType]
      properties:
        docType:
          type: STRING
          description: kind
          enum: [invoice, receipt]
        total:
          anyOf:
            - {type: NUMBER}
            - {type: 'null'}
          description: grand total
"""


async def test_import_transcodes_gemini_yaml_as_new_variant(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed(workspace, pid, chat_id, "chinhin.yaml", _GEMINI_YAML.encode("utf-8"))

    out = await import_schema_from_yaml(
        workspace, pid, chat_id, "chinhin.yaml", as_new_variant=True,
    )

    assert out["ok"] is True
    assert out["names"] == ["docType", "total"]
    # Self-indicating: the response tells the agent it auto-converted.
    assert out["converted_from"] == "json-schema"
    assert "prompt-config bundle" in out["notes"]
    # Active prompt untouched (as_new_variant contract).
    active = await read_active_prompt(workspace, pid)
    assert active.prompt_id != out["prompt_id"]


async def test_import_unrecognized_dict_gives_teaching_error(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed(workspace, pid, chat_id, "cfg.yaml", b"foo: 1\nbar: 2\n")
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "cfg.yaml")
    assert ei.value.error_code == "invalid_schema_yaml"
    # Teaching error points at where a real schema would live.
    assert "json_schema" in ei.value.error_message_en


async def test_import_aggregates_all_field_errors(workspace: Path) -> None:
    """A hand-edited list with several bad fields reports ALL of them in one
    error — the fail-fast one-per-re-import behaviour is what caused the loop."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    bad = (
        b"- name: a\n  type: array\n  description: missing items\n"
        b"- name: b\n  type: object\n  description: missing properties\n"
        b"- name: c\n  type: string\n  description: ok\n"
    )
    _seed(workspace, pid, chat_id, "bad.yaml", bad)
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "bad.yaml")
    msg = ei.value.error_message_en
    # Both bad fields named in a single error; the good one absent.
    assert "field[0] 'a'" in msg
    assert "field[1] 'b'" in msg
    assert "'c'" not in msg
