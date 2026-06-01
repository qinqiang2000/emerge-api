import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.tools.projects import create_project
from app.tools.docs import upload_doc
from app.tools.schema import write_schema
from app.tools.extract import extract_one
from app.schemas.schema_field import FieldType, SchemaField
from tests.conftest import make_provider_result


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf"


def _basic_schema() -> list[SchemaField]:
    return [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number"),
        SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total amount"),
    ]


async def test_extract_one_writes_prediction(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {
            "entities": [{"invoice_no": "INV-1", "total_amount": 1250.5}],
            "_evidence": [{"invoice_no": 1, "total_amount": 1}],
        }
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert out["entities"][0]["invoice_no"] == "INV-1"
    assert out["_evidence"][0]["invoice_no"]["page"] == 1

    pred = json.loads((workspace / pid / "predictions" / "_draft" / f"{did}.json").read_text())
    assert pred == out
    # M14 — every baseline write self-stamps. The stub provider runs the
    # default seeded model (Default · gemini-2.5-flash) and active prompt;
    # the blob must carry those identities under `_run`.
    assert "_run" in pred
    assert pred["_run"]["kind"] == "baseline"
    assert pred["_run"]["extract_model"] == "gemini-2.5-flash"
    assert pred["_run"]["run_id"].startswith("r_")


async def test_extract_one_model_override_resolves_project_model_id(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """`model_id="m_xxx"` (project-level id) was being passed straight to
    `get_provider_for_model`, which only prefix-matches `gemini|claude|anthropic`
    and 400'd on the `m_` prefix. The override path must resolve the project
    model_config first, then use its provider_model_id."""
    from app.tools.model import create_model

    pid = (await create_project(workspace, name="x"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)
    mid = await create_model(
        workspace, pid,
        label="Alt", provider="google", provider_model_id="gemini-3.5-flash",
    )
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "OVR", "total_amount": 1.0}],
         "_evidence": [{"invoice_no": 1, "total_amount": 1}]}
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider, model_id=mid)

    assert out["entities"][0]["invoice_no"] == "OVR"
    # Provider received the underlying provider_model_id, not the project m_* id.
    assert stub_provider.extract.await_args.kwargs["model_id"] == "gemini-3.5-flash"


async def test_extract_one_tool_returns_envelope_on_transient_provider_error(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """The 振兴_testset bug: a flaky proxy raised a bare httpx.ConnectError out
    of the provider, which propagated through the MCP wrapper and the SDK
    rendered it to the agent as an opaque `Command failed with no output`. The
    wrapper must instead hand back a structured, agent-readable envelope whose
    `transient` flag tells the agent to just re-run THIS doc."""
    import httpx
    import mcp.types as mcp_types
    from unittest.mock import MagicMock
    from app.tools import build_emerge_mcp

    pid = (await create_project(workspace, name="x"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    # Bare ConnectError — empty message, exactly what the proxy produced.
    stub_provider.extract.side_effect = httpx.ConnectError("")

    server = build_emerge_mcp(workspace=workspace, provider=stub_provider, job_runner=MagicMock())
    call_handler = server["instance"].request_handlers[mcp_types.CallToolRequest]
    req = mcp_types.CallToolRequest(
        method="tools/call",
        params=mcp_types.CallToolRequestParams(
            name="extract_one", arguments={"slug": pid, "filename": did},
        ),
    )
    result = await call_handler(req)
    payload = json.loads(result.root.content[0].text)  # type: ignore[index]

    assert payload["ok"] is False
    assert payload["error"]["error_code"] == "extract_provider_unavailable"
    assert payload["error"]["transient"] is True
    # Empty str(exc) must not collapse to a blank message — preserve the type.
    assert payload["error"]["error_message_en"] == "ConnectError"


async def test_extract_one_invalid_json_returns_error(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result({"wrong_top_level": "x"})

    with pytest.raises(ValueError, match="entities"):
        await extract_one(workspace, pid, did, provider=stub_provider)



async def test_extract_one_reads_schema_from_active_prompt(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """After M9.1, extract_one sources its schema from prompts/{active}.json
    via read_schema (not directly from schema.json)."""
    from app.tools.extract import extract_one
    from app.tools.docs import upload_doc
    from app.tools.prompt import write_prompt
    from app.tools.projects import create_project
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.migrate import migrate_project_if_needed
    from tests.conftest import make_provider_result

    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = (await upload_doc(workspace, pid, pdf_bytes, "a.pdf"))["filename"]
    # Bootstrap the prompt structure via migration, then write the schema
    await migrate_project_if_needed(workspace, pid)
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "X-1"}], "_evidence": [{"invoice_no": 1}]}
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert out["entities"][0]["invoice_no"] == "X-1"
    stub_provider.extract.assert_awaited_once()


def test_response_schema_marks_all_fields_required_and_nullable() -> None:
    """Every schema-declared field must appear in entity_schema.required and
    carry nullable:true, so Gemini always emits the key (using null when the
    value is absent). Schema definition == prediction key set."""
    from app.tools.extract import _build_response_schema

    schema = [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="d", required=True),
        SchemaField(name="total_amount", type=FieldType.NUMBER, description="d", required=False),
        SchemaField(
            name="line_items",
            type=FieldType.ARRAY,
            description="d",
            required=False,
            items=SchemaField(
                type=FieldType.OBJECT,
                description="row",
                properties=[
                    SchemaField(name="sku", type=FieldType.STRING, description="d"),
                    SchemaField(name="qty", type=FieldType.NUMBER, description="d"),
                ],
            ),
        ),
    ]
    rs = _build_response_schema(schema)
    entity = rs["properties"]["entities"]["items"]

    assert entity["required"] == ["invoice_no", "total_amount", "line_items"]
    for fname in ("invoice_no", "total_amount", "line_items"):
        assert entity["properties"][fname].get("nullable") is True, fname

    child_items = entity["properties"]["line_items"]["items"]
    assert child_items["required"] == ["sku", "qty"]
    for cname in ("sku", "qty"):
        assert child_items["properties"][cname].get("nullable") is True, cname


def test_enum_appears_both_in_schema_and_text_hint() -> None:
    """`enum` is a hard constraint via response_schema AND a text-block hint
    (belt-and-suspenders for providers that under-honor structural enums)."""
    from app.tools.extract import _build_response_schema, _build_field_instructions

    schema = [
        SchemaField(
            name="status",
            type=FieldType.STRING,
            description="Doc status",
            enum=["draft", "final"],
        ),
    ]
    props = _build_response_schema(schema)["properties"]["entities"]["items"]["properties"]
    assert props["status"]["enum"] == ["draft", "final"]
    assert "Allowed values: draft, final." in _build_field_instructions(schema)


async def test_extract_one_preserves_null_fields_in_prediction(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """When the LLM returns an explicit null for a schema field, the written
    prediction must keep the key (not strip it via exclude_none). Otherwise
    users see schema-defined fields silently disappear from output."""
    pid = (await create_project(workspace, name="x"))["slug"]
    did = (await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf"))["filename"]
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "INV-1", "total_amount": None}]}
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert "total_amount" in out["entities"][0]
    assert out["entities"][0]["total_amount"] is None

    pred = json.loads((workspace / pid / "predictions" / "_draft" / f"{did}.json").read_text())
    assert "total_amount" in pred["entities"][0]
    assert pred["entities"][0]["total_amount"] is None


async def test_extract_one_uses_active_model_id(
    workspace: Path, stub_provider: AsyncMock
) -> None:
    """When model_id arg is None, extract_one reads project.active_model_id
    and resolves the provider_model_id from models/{active}.json."""
    from app.tools.extract import extract_one
    from app.tools.docs import upload_doc
    from app.tools.model import create_model
    from app.tools.projects import create_project, update_project
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.migrate import migrate_project_if_needed
    from tests.conftest import make_provider_result

    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = (await upload_doc(workspace, pid, pdf_bytes, "a.pdf"))["filename"]
    # Bootstrap the prompt/model structure via migration
    await migrate_project_if_needed(workspace, pid)
    # Create a second model and switch active
    new_mid = await create_model(
        workspace, pid,
        label="Sonnet 4.6",
        provider="anthropic",
        provider_model_id="claude-sonnet-4-6",
    )
    await update_project(workspace, pid, {"active_model_id": new_mid})
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    )
    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "X-1"}], "_evidence": [{"invoice_no": 1}]}
    )

    await extract_one(workspace, pid, did, provider=stub_provider)

    # The provider was invoked with the active model's provider_model_id, not the legacy field
    call = stub_provider.extract.await_args
    assert call.kwargs["model_id"] == "claude-sonnet-4-6"


def test_response_schema_integer_type() -> None:
    from app.tools.extract import _build_response_schema

    schema = [SchemaField(name="page_count", type=FieldType.INTEGER, description="d")]
    rs = _build_response_schema(schema)
    prop = rs["properties"]["entities"]["items"]["properties"]["page_count"]
    assert prop["type"] == "integer"
    assert prop["nullable"] is True


def test_response_schema_string_format_date_time() -> None:
    from app.tools.extract import _build_response_schema
    from app.schemas.schema_field import StringFormat

    schema = [SchemaField(
        name="paid_at", type=FieldType.STRING,
        description="d", format=StringFormat.DATE_TIME,
    )]
    prop = _build_response_schema(schema)["properties"]["entities"]["items"]["properties"]["paid_at"]
    assert prop["type"] == "string"
    assert prop["format"] == "date-time"


def test_response_schema_nested_object() -> None:
    from app.tools.extract import _build_response_schema

    schema = [SchemaField(
        name="seller", type=FieldType.OBJECT, description="d",
        properties=[
            SchemaField(name="name", type=FieldType.STRING, description="d"),
            SchemaField(name="tax_id", type=FieldType.STRING, description="d"),
        ],
    )]
    obj = _build_response_schema(schema)["properties"]["entities"]["items"]["properties"]["seller"]
    assert obj["type"] == "object"
    assert obj["nullable"] is True
    assert set(obj["properties"].keys()) == {"name", "tax_id"}
    assert obj["required"] == ["name", "tax_id"]


def test_response_schema_array_of_string() -> None:
    from app.tools.extract import _build_response_schema

    schema = [SchemaField(
        name="keywords", type=FieldType.ARRAY, description="d",
        items=SchemaField(type=FieldType.STRING, description="kw"),
    )]
    prop = _build_response_schema(schema)["properties"]["entities"]["items"]["properties"]["keywords"]
    assert prop["type"] == "array"
    assert prop["items"]["type"] == "string"


def test_response_schema_array_of_integer() -> None:
    from app.tools.extract import _build_response_schema

    schema = [SchemaField(
        name="pages", type=FieldType.ARRAY, description="d",
        items=SchemaField(type=FieldType.INTEGER, description="p"),
    )]
    prop = _build_response_schema(schema)["properties"]["entities"]["items"]["properties"]["pages"]
    assert prop["items"]["type"] == "integer"


def test_field_instructions_dot_paths_for_nested() -> None:
    from app.tools.extract import _build_field_instructions

    schema = [
        SchemaField(
            name="seller", type=FieldType.OBJECT, description="party",
            properties=[
                SchemaField(name="name", type=FieldType.STRING, description="seller name"),
                SchemaField(name="tax_id", type=FieldType.STRING, description="tax id"),
            ],
        ),
        SchemaField(
            name="line_items", type=FieldType.ARRAY, description="rows",
            items=SchemaField(
                type=FieldType.OBJECT, description="row",
                properties=[SchemaField(name="sku", type=FieldType.STRING, description="sku id")],
            ),
        ),
    ]
    text = _build_field_instructions(schema)
    assert "`seller.name`" in text
    assert "`seller.tax_id`" in text
    assert "`line_items[].sku`" in text


def test_legacy_array_object_extracts_to_new_response_schema() -> None:
    """A SchemaField fed legacy `{type:'array<object>', children:[...]}` dict
    must produce the same response_schema as the new shape."""
    from app.tools.extract import _build_response_schema

    legacy = SchemaField(**{
        "name": "line_items",
        "type": "array<object>",
        "description": "d",
        "children": [
            {"name": "sku", "type": "string", "description": "d"},
            {"name": "qty", "type": "number", "description": "d"},
        ],
    })
    rs = _build_response_schema([legacy])
    arr = rs["properties"]["entities"]["items"]["properties"]["line_items"]
    assert arr["type"] == "array"
    assert arr["items"]["type"] == "object"
    assert arr["items"]["required"] == ["sku", "qty"]
