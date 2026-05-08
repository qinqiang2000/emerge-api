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
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {
            "entities": [{"invoice_no": "INV-1", "total_amount": 1250.5}],
            "_evidence": [{"invoice_no": 1, "total_amount": 1}],
        }
    )

    out = await extract_one(workspace, pid, did, provider=stub_provider)
    assert out["entities"][0]["invoice_no"] == "INV-1"
    assert out["_evidence"][0]["invoice_no"] == 1

    pred = json.loads((workspace / pid / "predictions" / "_draft" / f"{did}.json").read_text())
    assert pred == out


async def test_extract_one_invalid_json_returns_error(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    did = await upload_doc(workspace, pid, _FIXTURE.read_bytes(), "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result({"wrong_top_level": "x"})

    with pytest.raises(ValueError, match="entities"):
        await extract_one(workspace, pid, did, provider=stub_provider)
