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


from app.tools.extract import extract_batch


async def test_extract_batch_runs_all_docs(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    pdf = _FIXTURE.read_bytes()
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    d2 = await upload_doc(workspace, pid, pdf, "b.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.return_value = make_provider_result(
        {"entities": [{"invoice_no": "X", "total_amount": 1.0}], "_evidence": [{"invoice_no": 1, "total_amount": 1}]}
    )

    summary = await extract_batch(workspace, pid, [d1, d2], provider=stub_provider, concurrency=2)
    assert summary["ok_count"] == 2
    assert summary["err_count"] == 0
    assert set(summary["per_doc"].keys()) == {d1, d2}
    # entities now bubble up so agent can summarize without re-calling extract_one
    assert summary["per_doc"][d1]["entities"] == [{"invoice_no": "X", "total_amount": 1.0}]
    assert summary["per_doc"][d2]["entities"] == [{"invoice_no": "X", "total_amount": 1.0}]


async def test_extract_batch_records_per_doc_errors(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = await create_project(workspace, name="x")
    pdf = _FIXTURE.read_bytes()
    d1 = await upload_doc(workspace, pid, pdf, "a.pdf")
    await write_schema(workspace, pid, _basic_schema(), reason="init", allow_structural=True)

    stub_provider.extract.side_effect = ValueError("boom")
    summary = await extract_batch(workspace, pid, [d1], provider=stub_provider)
    assert summary["ok_count"] == 0
    assert summary["err_count"] == 1
    assert summary["per_doc"][d1]["ok"] is False
    assert "boom" in summary["per_doc"][d1]["error"]


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

    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")
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

    pid = await create_project(workspace, name="x")
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    did = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")
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
