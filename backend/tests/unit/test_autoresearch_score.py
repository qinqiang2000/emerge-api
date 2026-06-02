from pathlib import Path
from unittest.mock import AsyncMock

from app.jobs.autoresearch import score_with_schema
from app.provider.base import ProviderResult
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed


async def test_score_with_schema_runs_extract_then_score(workspace: Path) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    pdf = b"%PDF-1.4\n%%EOF\n"
    meta = await upload_doc(workspace, pid, pdf, "a.pdf")
    filename = meta["filename"]
    await save_reviewed(
        workspace, pid, filename,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )
    schema = [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")]

    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"invoice_no": "INV-1"}]},
        model_id="stub",
    )

    score_result, predictions = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    # M12.x: headline switched to field_accuracy_macro.
    assert score_result.field_accuracy_macro == 1.0
    assert predictions == {filename: [{"invoice_no": "INV-1"}]}


async def test_score_with_schema_caches_baseline_extract(workspace: Path) -> None:
    """Second eval pass over an unchanged (schema, model, docs) triple hits the
    baseline cache and skips the provider entirely — same predictions out."""
    pid = (await create_project(workspace, name="t"))["slug"]
    pdf = b"%PDF-1.4\n%%EOF\n"
    meta = await upload_doc(workspace, pid, pdf, "a.pdf")
    filename = meta["filename"]
    await save_reviewed(
        workspace, pid, filename,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )
    schema = [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")]

    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"invoice_no": "INV-1"}]},
        model_id="stub",
    )

    _, preds1 = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    assert provider.extract.call_count == 1  # cold cache → one real call

    _, preds2 = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    # Warm cache → no further provider round-trips, identical predictions.
    assert provider.extract.call_count == 1
    assert preds2 == preds1 == {filename: [{"invoice_no": "INV-1"}]}


async def test_score_with_schema_cache_misses_on_schema_change(workspace: Path) -> None:
    """Rewording a field description bumps the schema_hash → cache miss → the
    provider is hit again (proves the key isn't stale across descriptions)."""
    pid = (await create_project(workspace, name="t"))["slug"]
    pdf = b"%PDF-1.4\n%%EOF\n"
    meta = await upload_doc(workspace, pid, pdf, "a.pdf")
    filename = meta["filename"]
    await save_reviewed(
        workspace, pid, filename,
        entities=[{"invoice_no": "INV-1"}],
        source=ReviewedSource.MANUAL,
    )
    provider = AsyncMock()
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"invoice_no": "INV-1"}]},
        model_id="stub",
    )

    await score_with_schema(
        workspace=workspace, project_id=pid,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
        provider=provider, model_id="stub",
    )
    await score_with_schema(
        workspace=workspace, project_id=pid,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="REWORDED")],
        provider=provider, model_id="stub",
    )
    assert provider.extract.call_count == 2


async def test_score_with_schema_returns_zero_when_reviewed_empty(workspace: Path) -> None:
    pid = (await create_project(workspace, name="t"))["slug"]
    schema = [SchemaField(name="invoice_no", type=FieldType.STRING, description="d")]
    provider = AsyncMock()
    score_result, predictions = await score_with_schema(
        workspace=workspace, project_id=pid, schema=schema,
        provider=provider, model_id="stub",
    )
    assert score_result.n_reviewed == 0
    assert predictions == {}
    provider.extract.assert_not_called()
