"""Phase D — `import_schema_from_yaml` tool + HTTP mirror.

Covers the tool body directly (parse / validate / write through the same
`write_schema` writer that the agent uses) plus the HTTP mirror behaviour
(`POST /lab/projects/{slug}/chats/{chat_id}/attachments/{filename:path}/import-schema`).

The matrix:

- happy path: yaml file with 3 fields → schema replaced, return shape correct
- invalid yaml (broken syntax) → SchemaImportError + 400 with `invalid_schema_yaml`
- valid yaml but list of strings (not field dicts) → pydantic surfaces as `invalid_schema_yaml`
- file with `.pdf` ext → refused before parse (`import_schema_unsupported_ext`)
- chat attachment missing → FileNotFoundError + HTTP 404
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.tools.prompt import list_prompts, read_active_prompt, read_prompt
from app.tools.schema import (
    SchemaImportError,
    import_schema_from_yaml,
    read_schema,
)
from app.workspace.paths import chat_attachments_dir


_VALID_YAML = """- name: invoice_number
  type: string
  description: id printed at the top right
  required: true
- name: total_amount
  type: number
  description: invoice total in transaction currency
- name: line_items
  type: array
  description: line item rows
  items:
    type: object
    description: one line on the invoice
    properties:
      - name: description
        type: string
        description: line description
      - name: amount
        type: number
        description: line amount
"""


def _seed_attachment(workspace: Path, slug: str, chat_id: str, filename: str, body: bytes) -> Path:
    target_dir = chat_attachments_dir(workspace, slug, chat_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    p = target_dir / filename
    p.write_bytes(body)
    return p


async def test_import_schema_from_yaml_replaces_schema(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "fields.yaml", _VALID_YAML.encode("utf-8"))

    out = await import_schema_from_yaml(workspace, pid, chat_id, "fields.yaml")

    assert out["ok"] is True
    assert out["field_count"] == 3
    assert out["names"] == ["invoice_number", "total_amount", "line_items"]
    # Schema actually flipped on disk — read_schema goes through the same
    # active-prompt path the agent reads, so this also validates the writer.
    schema = await read_schema(workspace, pid)
    assert [f.name for f in schema] == [
        "invoice_number", "total_amount", "line_items",
    ]


async def test_import_schema_from_yaml_as_new_variant_keeps_active(workspace: Path) -> None:
    """as_new_variant=True mints a new prompt variant and leaves the active
    prompt's schema untouched — the user must switch_active_prompt to adopt."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "fields.yaml", _VALID_YAML.encode("utf-8"))

    active_before = await read_active_prompt(workspace, pid)

    out = await import_schema_from_yaml(
        workspace, pid, chat_id, "fields.yaml", as_new_variant=True,
    )

    assert out["ok"] is True
    assert out["as_new_variant"] is True
    assert out["field_count"] == 3
    new_id = out["prompt_id"]
    assert out["label"] == "imported:fields.yaml"

    # Active prompt is unchanged on disk.
    active_after = await read_active_prompt(workspace, pid)
    assert active_after.prompt_id == active_before.prompt_id
    assert [f.name for f in active_after.schema] == [f.name for f in active_before.schema]

    # The new variant exists, carries the imported schema, and is NOT active.
    new_variant = await read_prompt(workspace, pid, new_id)
    assert [f.name for f in new_variant.schema] == [
        "invoice_number", "total_amount", "line_items",
    ]
    rows = {r["prompt_id"]: r for r in await list_prompts(workspace, pid)}
    assert rows[new_id]["is_active"] is False
    assert rows[active_before.prompt_id]["is_active"] is True


async def test_import_schema_from_yaml_as_new_variant_custom_label(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "fields.yaml", _VALID_YAML.encode("utf-8"))
    out = await import_schema_from_yaml(
        workspace, pid, chat_id, "fields.yaml",
        as_new_variant=True, new_label="chinhin v2",
    )
    assert out["label"] == "chinhin v2"
    assert (await read_prompt(workspace, pid, out["prompt_id"])).label == "chinhin v2"


async def test_http_import_schema_from_yaml_as_new_variant(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "fields.yaml", _VALID_YAML.encode("utf-8"))
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/fields.yaml/import-schema",
        json={"as_new_variant": True, "new_label": "from http"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_new_variant"] is True
    assert body["label"] == "from http"
    assert body["field_count"] == 3


async def test_import_schema_from_yaml_handles_json_payload(workspace: Path) -> None:
    """JSON is a strict YAML subset — `yaml.safe_load` parses it, so the
    same import path covers `.json` exports without a separate parser."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    body = (
        b'[{"name": "buyer_name", "type": "string", "description": "x"}, '
        b'{"name": "amount", "type": "number", "description": "y"}]'
    )
    _seed_attachment(workspace, pid, chat_id, "fields.json", body)
    out = await import_schema_from_yaml(workspace, pid, chat_id, "fields.json")
    assert out["field_count"] == 2
    assert out["names"] == ["buyer_name", "amount"]


async def test_import_schema_from_yaml_rejects_bad_yaml(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    # Unbalanced bracket — `yaml.safe_load` raises YAMLError.
    _seed_attachment(workspace, pid, chat_id, "broken.yaml", b"- foo: [bar\n")
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "broken.yaml")
    assert ei.value.error_code == "invalid_schema_yaml"


async def test_import_schema_from_yaml_rejects_non_list_root(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "obj.yaml", b"foo: 1\nbar: 2\n")
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "obj.yaml")
    assert ei.value.error_code == "invalid_schema_yaml"


async def test_import_schema_from_yaml_rejects_list_of_strings(workspace: Path) -> None:
    """A yaml file whose root is a list of plain strings parses fine but
    pydantic refuses; surface as `invalid_schema_yaml`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "strings.yaml", b"- foo\n- bar\n- baz\n")
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "strings.yaml")
    assert ei.value.error_code == "invalid_schema_yaml"


async def test_import_schema_from_yaml_refuses_pdf_extension(workspace: Path) -> None:
    """We refuse upfront on extension before reading bytes — so a `.pdf`
    drop never reaches the YAML parser."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "scan.pdf", b"%PDF-1.4\n%%EOF\n")
    with pytest.raises(SchemaImportError) as ei:
        await import_schema_from_yaml(workspace, pid, chat_id, "scan.pdf")
    assert ei.value.error_code == "import_schema_unsupported_ext"


async def test_import_schema_from_yaml_missing_attachment(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    with pytest.raises(FileNotFoundError):
        await import_schema_from_yaml(
            workspace, pid, chat_id, "ghost.yaml",
        )


# ── HTTP mirror ─────────────────────────────────────────────────────────────


async def test_http_import_schema_from_yaml_happy_path(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    # Seed the chat attachment via the public route so we exercise the same
    # path a frontend would take (drop → claim/attach → import).
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attach",
        files={"file": ("fields.yaml", io.BytesIO(_VALID_YAML.encode("utf-8")), "text/yaml")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "schema"

    r2 = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/fields.yaml/import-schema",
        json={"allow_structural": True},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert body["field_count"] == 3
    assert body["names"] == ["invoice_number", "total_amount", "line_items"]


async def test_http_import_schema_from_yaml_no_body_defaults_allow_structural(
    workspace: Path,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "fields.yaml", _VALID_YAML.encode("utf-8"))
    client = TestClient(app)
    # No body → treat as default allow_structural=true.
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/fields.yaml/import-schema",
    )
    assert r.status_code == 200, r.text
    assert r.json()["field_count"] == 3


async def test_http_import_schema_from_yaml_invalid_yaml(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "broken.yaml", b"- foo: [bar\n")
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/broken.yaml/import-schema",
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["error_code"] == "invalid_schema_yaml"


async def test_http_import_schema_from_yaml_unsupported_ext(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    _seed_attachment(workspace, pid, chat_id, "scan.pdf", b"%PDF-1.4\n%%EOF\n")
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/scan.pdf/import-schema",
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "import_schema_unsupported_ext"


async def test_http_import_schema_from_yaml_missing_attachment(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{pid}/chats/{chat_id}/attachments/ghost.yaml/import-schema",
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "attachment_not_found"


async def test_http_import_schema_from_yaml_unknown_project() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/no-such/chats/c_abc123def456/attachments/fields.yaml/import-schema",
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"
