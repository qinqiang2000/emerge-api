import base64
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.provider.base import Provider, ProviderResult
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.extract import extract_bytes_with_schema


@pytest.mark.asyncio
async def test_extract_bytes_does_not_touch_workspace(tmp_path: Path) -> None:
    schema = [SchemaField(name="x", type=FieldType.STRING, description="x")]
    provider = AsyncMock(spec=Provider)
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"x": "hello"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    out = await extract_bytes_with_schema(
        content=b"%PDF-1.4 fake bytes",
        filename="invoice.pdf",
        schema=schema,
        provider=provider,
        model_id="claude-sonnet-4-6",
    )
    assert out["entities"] == [{"x": "hello"}]
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert after == before


@pytest.mark.asyncio
async def test_extract_bytes_passes_pdf_block_to_provider() -> None:
    schema = [SchemaField(name="x", type=FieldType.STRING, description="x")]
    provider = AsyncMock(spec=Provider)
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"x": "v"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    payload = b"%PDF-1.4 hi"
    await extract_bytes_with_schema(
        content=payload, filename="x.pdf",
        schema=schema, provider=provider, model_id="claude-sonnet-4-6",
    )
    call = provider.extract.await_args
    user_content = call.kwargs["user_content"]
    doc_block = user_content[1]
    assert getattr(doc_block, "media_type", None) == "application/pdf"
    assert getattr(doc_block, "data_b64", None) == base64.b64encode(payload).decode("ascii")


@pytest.mark.asyncio
async def test_extract_bytes_rejects_unknown_extension() -> None:
    schema = [SchemaField(name="x", type=FieldType.STRING, description="x")]
    provider = AsyncMock(spec=Provider)
    with pytest.raises(ValueError, match="unsupported"):
        await extract_bytes_with_schema(
            content=b"raw", filename="x.exe",
            schema=schema, provider=provider, model_id="claude-sonnet-4-6",
        )


@pytest.mark.asyncio
async def test_extract_bytes_image_block_for_png() -> None:
    schema = [SchemaField(name="x", type=FieldType.STRING, description="x")]
    provider = AsyncMock(spec=Provider)
    provider.extract.return_value = ProviderResult(
        raw_json={"entities": []},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    await extract_bytes_with_schema(
        content=b"\x89PNG\r\n", filename="rcpt.png",
        schema=schema, provider=provider, model_id="claude-sonnet-4-6",
    )
    user_content = provider.extract.await_args.kwargs["user_content"]
    assert user_content[1].media_type == "image/png"
