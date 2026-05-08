import pytest
from pydantic import ValidationError

from app.schemas.schema_field import SchemaField, FieldType


def test_simple_field_minimal() -> None:
    f = SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")
    assert f.name == "invoice_no"
    assert f.type == FieldType.STRING
    assert f.required is False  # default
    assert f.examples is None
    assert f.enum is None
    assert f.children is None


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


def test_array_object_requires_children() -> None:
    with pytest.raises(ValidationError):
        SchemaField(name="line_items", type=FieldType.ARRAY_OBJECT, description="x")


def test_array_object_with_children_ok() -> None:
    f = SchemaField(
        name="line_items",
        type=FieldType.ARRAY_OBJECT,
        description="x",
        children=[
            SchemaField(name="qty", type=FieldType.NUMBER, description="qty"),
            SchemaField(name="unit_price", type=FieldType.NUMBER, description="price"),
        ],
    )
    assert len(f.children) == 2  # type: ignore[arg-type]


def test_serializes_round_trip() -> None:
    f = SchemaField(name="x", type=FieldType.STRING, description="d", required=True)
    blob = f.model_dump()
    f2 = SchemaField(**blob)
    assert f == f2
