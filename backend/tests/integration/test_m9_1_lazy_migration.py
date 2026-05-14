"""M9.1 — end-to-end: a legacy on-disk project transparently upgrades to the
new layout the first time its schema is touched, without any explicit migrate
step from the caller. Also covers the fresh-project happy path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_legacy_project(workspace: Path, pid: str) -> None:
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "legacy invoice",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }), encoding="utf-8")
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": False},
        {"name": "total", "type": "number", "description": "Total amount", "required": True},
    ]), encoding="utf-8")
    (pdir / "global_notes.md").write_text("US invoice; USD only.", encoding="utf-8")


async def test_fresh_project_directly_writes_new_layout(workspace: Path) -> None:
    from app.tools.projects import create_project
    pid = (await create_project(workspace, name="fresh"))["slug"]
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()
    assert (workspace / pid / "models" / "m_default.json").exists()
    assert not (workspace / pid / "schema.json").exists()


async def test_legacy_project_migrates_on_read_schema(workspace: Path) -> None:
    from app.tools.schema import read_schema
    pid = "p_legacy00read"
    _build_legacy_project(workspace, pid)
    fields = await read_schema(workspace, pid)
    assert len(fields) == 2
    # post-migration artifacts on disk
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()
    assert (workspace / pid / "models" / "m_default.json").exists()


async def test_legacy_project_migrates_on_list_projects(workspace: Path) -> None:
    from app.tools.projects import list_projects
    pid = "p_legacy00list"
    _build_legacy_project(workspace, pid)
    items = await list_projects(workspace)
    assert any(it["project_id"] == pid for it in items)
    # list_projects iterates with migration in the loop, so the prompts dir exists now
    assert (workspace / pid / "prompts" / "pr_baseline.json").exists()


async def test_legacy_project_write_schema_then_read_round_trips(workspace: Path) -> None:
    """Writing through the legacy write_schema entrypoint also migrates and
    leaves the canonical state in prompts/{active}.json."""
    from app.tools.schema import read_schema, write_schema
    from app.schemas.schema_field import FieldType, SchemaField

    pid = "p_legacy00wrt"
    _build_legacy_project(workspace, pid)

    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="updated description")],
        reason="post-migration first edit",
        allow_structural=True,
    )
    fields = await read_schema(workspace, pid)
    assert len(fields) == 1
    assert fields[0].description == "updated description"

    # global_notes was preserved through the wrapper (it folded the legacy global_notes.md
    # into pr_baseline.global_notes during migration, and write_schema preserved it)
    pv_blob = json.loads((workspace / pid / "prompts" / "pr_baseline.json").read_text())
    assert pv_blob["global_notes"] == "US invoice; USD only."
