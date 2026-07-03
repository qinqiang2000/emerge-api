import json
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.tools.schema import read_schema, write_schema, StructuralChangeError
from app.schemas.schema_field import FieldType, SchemaField


def _f(name: str, **kw: object) -> SchemaField:
    defaults: dict[str, object] = {"description": "d"}
    defaults.update(kw)
    return SchemaField(name=name, type=FieldType.STRING, **defaults)  # type: ignore[arg-type]


async def test_read_schema_empty_after_create(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    assert await read_schema(workspace, pid) == []


async def test_write_schema_persists(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await write_schema(workspace, pid, [_f("invoice_no")], reason="initial", allow_structural=True)
    got = await read_schema(workspace, pid)
    assert len(got) == 1
    assert got[0].name == "invoice_no"


async def test_write_schema_blocks_structural_change_without_flag(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await write_schema(workspace, pid, [_f("a")], reason="init", allow_structural=True)
    with pytest.raises(StructuralChangeError):
        await write_schema(workspace, pid, [_f("a"), _f("b")], reason="add b")


async def test_write_schema_allows_description_edit(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    await write_schema(workspace, pid, [_f("a", description="old")], reason="init", allow_structural=True)
    await write_schema(workspace, pid, [_f("a", description="new")], reason="edit text")
    got = await read_schema(workspace, pid)
    assert got[0].description == "new"


from unittest.mock import AsyncMock

from app.tools.schema import derive_schema
from app.tools.docs import upload_doc
from tests.conftest import make_provider_result


async def test_derive_schema_calls_provider(workspace: Path, stub_provider: AsyncMock) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    meta = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")

    stub_provider.extract.return_value = make_provider_result(
        {
            "fields": [
                {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": True},
                {"name": "total_amount", "type": "number", "description": "Total amount", "required": True},
            ]
        }
    )

    fields = await derive_schema(
        workspace,
        pid,
        sample_filenames=[meta["filename"]],
        intent="extract core invoice info",
        provider=stub_provider,
        model_id="stub-model",
    )
    assert len(fields) == 2
    names = {f.name for f in fields}
    assert names == {"invoice_no", "total_amount"}
    stub_provider.extract.assert_awaited_once()


async def test_derive_schema_scrubs_proposer_noise(workspace: Path, stub_provider: AsyncMock) -> None:
    """Proposer LLM occasionally hangs format/enum on non-string types, or items on
    non-array types — response_schema can't express the cross-field rule. The tool
    must scrub those毛刺 instead of failing the whole call (the schema gets edited
    downstream anyway)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    meta = await upload_doc(workspace, pid, pdf_bytes, "a.pdf")

    stub_provider.extract.return_value = make_provider_result(
        {
            "fields": [
                # format on type=number → must be stripped
                {"name": "total", "type": "number", "description": "d", "format": "date"},
                # array with items that wrongly carries format on type=object → strip nested format
                {
                    "name": "line_items",
                    "type": "array",
                    "description": "d",
                    "items": {
                        "type": "object",
                        "description": "d",
                        "format": "date",
                        "properties": [
                            {"name": "sku", "type": "string", "description": "d"},
                        ],
                    },
                },
                # clean field passes through
                {"name": "invoice_no", "type": "string", "description": "d"},
            ]
        }
    )

    fields = await derive_schema(
        workspace, pid,
        sample_filenames=[meta["filename"]],
        intent="x",
        provider=stub_provider,
        model_id="stub-model",
    )
    by_name = {f.name: f for f in fields}
    assert set(by_name) == {"total", "line_items", "invoice_no"}
    assert by_name["total"].format is None
    assert by_name["line_items"].items is not None
    assert by_name["line_items"].items.format is None


async def test_write_schema_writes_to_active_prompt_not_schema_json(workspace: Path) -> None:
    """After M9.1, write_schema is a thin wrapper over write_prompt; the canonical
    storage for active descriptions is prompts/{active}.json, not schema.json."""
    from app.workspace.paths import prompt_path
    pid = (await create_project(workspace, name="x"))["slug"]
    await write_schema(
        workspace, pid,
        [_f("invoice_no")],
        reason="initial",
        allow_structural=True,
    )
    pp = prompt_path(workspace, pid, "pr_baseline")
    assert pp.exists()
    pv = json.loads(pp.read_text())
    assert len(pv["schema"]) == 1
    assert pv["schema"][0]["name"] == "invoice_no"


async def test_write_schema_preserves_global_notes(workspace: Path) -> None:
    """The wrapper must NOT clobber global_notes when only fields are being updated."""
    from app.tools.prompt import write_prompt
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.paths import prompt_path
    from app.workspace.migrate import migrate_project_if_needed
    pid = (await create_project(workspace, name="x"))["slug"]
    # Ensure migration has run so active_prompt_id exists before writing directly
    await migrate_project_if_needed(workspace, pid)
    # Seed global_notes via write_prompt directly
    await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=[SchemaField(name="a", type=FieldType.STRING, description="d")],
        global_notes="some legacy notes",
    )
    # Now agent does a schema-only change through write_schema
    await write_schema(
        workspace, pid,
        [_f("a", description="new")],
        reason="edit",
    )
    pv = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert pv["global_notes"] == "some legacy notes"
    assert pv["schema"][0]["description"] == "new"


# ── _bytes_to_block: text docs become a plain TextBlock, binary docs unchanged ──

from app.provider.base import DocumentBlock, ImageBlock, TextBlock
from app.tools.schema import _bytes_to_block


def test_bytes_to_block_json_returns_textblock() -> None:
    block = _bytes_to_block(b'{"a": 1}', "json")
    assert isinstance(block, TextBlock)
    assert block.text == '{"a": 1}'


def test_bytes_to_block_text_extensions_all_return_textblock() -> None:
    for ext in ("txt", "md", "csv", "yaml", "yml"):
        block = _bytes_to_block(b"a * b = c\n", ext)
        assert isinstance(block, TextBlock), ext
        assert block.text == "a * b = c\n"


def test_bytes_to_block_pdf_unchanged() -> None:
    block = _bytes_to_block(b"%PDF-1.4 fake", "pdf")
    assert isinstance(block, DocumentBlock)
    assert block.media_type == "application/pdf"


def test_bytes_to_block_png_and_jpg_unchanged() -> None:
    png = _bytes_to_block(b"\x89PNG\r\n\x1a\n....", "png")
    assert isinstance(png, ImageBlock) and png.media_type == "image/png"
    jpg = _bytes_to_block(b"\xff\xd8\xff....", "jpg")
    assert isinstance(jpg, ImageBlock) and jpg.media_type == "image/jpeg"


def test_bytes_to_block_rejects_unsupported_ext() -> None:
    with pytest.raises(ValueError, match="unsupported file extension"):
        _bytes_to_block(b"MZ....", "exe")
