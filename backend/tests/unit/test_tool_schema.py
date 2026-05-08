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
    pid = await create_project(workspace, name="x")
    assert await read_schema(workspace, pid) == []


async def test_write_schema_persists(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("invoice_no")], reason="initial", allow_structural=True)
    got = await read_schema(workspace, pid)
    assert len(got) == 1
    assert got[0].name == "invoice_no"


async def test_write_schema_blocks_structural_change_without_flag(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("a")], reason="init", allow_structural=True)
    with pytest.raises(StructuralChangeError):
        await write_schema(workspace, pid, [_f("a"), _f("b")], reason="add b")


async def test_write_schema_allows_description_edit(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await write_schema(workspace, pid, [_f("a", description="old")], reason="init", allow_structural=True)
    await write_schema(workspace, pid, [_f("a", description="new")], reason="edit text")
    got = await read_schema(workspace, pid)
    assert got[0].description == "new"
