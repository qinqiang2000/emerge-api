import pytest
from pydantic import ValidationError

from app.schemas.schema_field import SchemaField, FieldType, StringFormat


def test_simple_field_minimal() -> None:
    f = SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")
    assert f.name == "invoice_no"
    assert f.type == FieldType.STRING
    assert f.required is False  # default
    assert f.enum is None
    assert f.properties is None
    assert f.items is None
    assert f.format is None


def test_field_name_must_be_snake_case() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="InvoiceNo", type=FieldType.STRING, description="x")
    with pytest.raises(ValidationError):
        SchemaField(name="invoice-no", type=FieldType.STRING, description="x")


def test_enum_field() -> None:
    f = SchemaField(
        name="document_type",
        type=FieldType.STRING,
        description="kind of doc",
        enum=["invoice", "others"],
    )
    assert f.enum == ["invoice", "others"]


def test_integer_type() -> None:
    f = SchemaField(name="page_count", type=FieldType.INTEGER, description="num pages")
    assert f.type == FieldType.INTEGER


def test_object_requires_non_empty_properties() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="seller", type=FieldType.OBJECT, description="x")
    with pytest.raises(ValidationError):
        SchemaField(name="seller", type=FieldType.OBJECT, description="x", properties=[])


def test_object_with_properties_ok() -> None:
    f = SchemaField(
        name="seller",
        type=FieldType.OBJECT,
        description="seller party",
        properties=[
            SchemaField(name="name", type=FieldType.STRING, description="seller name"),
            SchemaField(name="tax_id", type=FieldType.STRING, description="tax id"),
        ],
    )
    assert f.properties is not None and len(f.properties) == 2


def test_array_requires_items() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="keywords", type=FieldType.ARRAY, description="x")


def test_array_of_string_items() -> None:
    f = SchemaField(
        name="keywords",
        type=FieldType.ARRAY,
        description="kw list",
        items=SchemaField(type=FieldType.STRING, description="one keyword"),
    )
    assert f.items is not None and f.items.type == FieldType.STRING
    assert f.items.name is None


def test_array_of_integer_items() -> None:
    f = SchemaField(
        name="pages",
        type=FieldType.ARRAY,
        description="page refs",
        items=SchemaField(type=FieldType.INTEGER, description="page num"),
    )
    assert f.items is not None and f.items.type == FieldType.INTEGER


def test_array_of_object_items() -> None:
    f = SchemaField(
        name="line_items",
        type=FieldType.ARRAY,
        description="rows",
        items=SchemaField(
            type=FieldType.OBJECT,
            description="row",
            properties=[
                SchemaField(name="sku", type=FieldType.STRING, description="d"),
                SchemaField(name="qty", type=FieldType.INTEGER, description="d"),
            ],
        ),
    )
    assert f.items is not None and f.items.type == FieldType.OBJECT
    assert f.items.properties is not None and len(f.items.properties) == 2


def test_array_item_must_not_have_name() -> None:
    with pytest.raises(ValidationError):
        SchemaField(
            name="x",
            type=FieldType.ARRAY,
            description="d",
            items=SchemaField(name="item", type=FieldType.STRING, description="d"),
        )


def test_string_format_date_time() -> None:
    f = SchemaField(
        name="paid_at", type=FieldType.STRING,
        description="when paid",
        format=StringFormat.DATE_TIME,
    )
    assert f.format == StringFormat.DATE_TIME


def test_format_only_valid_on_string() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="n", type=FieldType.NUMBER, description="d", format=StringFormat.DATE)


def test_enum_only_valid_on_string() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="n", type=FieldType.INTEGER, description="d", enum=["1", "2"])


def test_properties_not_allowed_on_non_object() -> None:
    with pytest.raises(ValidationError):
        SchemaField(
            name="n", type=FieldType.STRING, description="d",
            properties=[SchemaField(name="a", type=FieldType.STRING, description="d")],
        )


def test_items_not_allowed_on_non_array() -> None:
    with pytest.raises(ValidationError):
        SchemaField(
            name="n", type=FieldType.STRING, description="d",
            items=SchemaField(type=FieldType.STRING, description="d"),
        )


def test_legacy_date_normalizes_to_string_format() -> None:
    """Old schema.json blobs use `{type:"date"}` — should round-trip into
    string+format=date so old projects load without migration."""
    f = SchemaField(**{"name": "due_date", "type": "date", "description": "d"})
    assert f.type == FieldType.STRING
    assert f.format == StringFormat.DATE


def test_legacy_array_object_normalizes_to_new_shape() -> None:
    blob = {
        "name": "line_items",
        "type": "array<object>",
        "description": "rows",
        "children": [
            {"name": "sku", "type": "string", "description": "d"},
            {"name": "qty", "type": "number", "description": "d"},
        ],
    }
    f = SchemaField(**blob)
    assert f.type == FieldType.ARRAY
    assert f.items is not None
    assert f.items.type == FieldType.OBJECT
    assert f.items.properties is not None
    assert [c.name for c in f.items.properties] == ["sku", "qty"]
    # idempotent — re-feeding the dumped blob produces the same model
    f2 = SchemaField(**f.model_dump(mode="json"))
    assert f2 == f


def test_legacy_date_inside_array_object_normalizes() -> None:
    """A legacy `date` child inside a legacy `array<object>` must also upgrade."""
    blob = {
        "name": "line_items",
        "type": "array<object>",
        "description": "rows",
        "children": [{"name": "billed_on", "type": "date", "description": "d"}],
    }
    f = SchemaField(**blob)
    assert f.items is not None and f.items.properties is not None
    inner = f.items.properties[0]
    assert inner.type == FieldType.STRING
    assert inner.format == StringFormat.DATE


def test_serializes_round_trip() -> None:
    f = SchemaField(name="x", type=FieldType.STRING, description="d", required=True)
    blob = f.model_dump()
    f2 = SchemaField(**blob)
    assert f == f2


from app.schemas.envelope import ErrorEnvelope, ToolResult


def test_error_envelope() -> None:
    e = ErrorEnvelope(error_code="provider_timeout", error_message_en="timed out")
    assert e.error_code == "provider_timeout"
    assert e.error_message_en == "timed out"


def test_tool_result_ok() -> None:
    r: ToolResult[dict] = ToolResult(ok=True, data={"x": 1})
    assert r.ok
    assert r.data == {"x": 1}
    assert r.error is None


def test_tool_result_err() -> None:
    err = ErrorEnvelope(error_code="x", error_message_en="y")
    r: ToolResult[dict] = ToolResult(ok=False, error=err)
    assert not r.ok
    assert r.data is None
    assert r.error is not None
    assert r.error.error_code == "x"


from app.schemas.extraction import ExtractionOutput


def test_extraction_output_minimal() -> None:
    o = ExtractionOutput(entities=[{"document_type": "invoice"}])
    assert o.entities == [{"document_type": "invoice"}]
    assert o.evidence is None


def test_extraction_output_with_evidence() -> None:
    o = ExtractionOutput(
        entities=[{"document_type": "invoice", "invoice_no": "INV-1"}],
        evidence=[{"document_type": 1, "invoice_no": 1}],
    )
    assert o.evidence == [{"document_type": 1, "invoice_no": 1}]


def test_extraction_evidence_must_match_entities_length() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionOutput(
            entities=[{"a": "x"}, {"a": "y"}],
            evidence=[{"a": 1}],
        )
