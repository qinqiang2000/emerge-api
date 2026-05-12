from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.schemas.prompt_variant import PromptVariant
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.prompt import (
    PromptNotFoundError,
    list_prompts,
    read_active_prompt,
    read_prompt,
    write_prompt,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_active_project(workspace: Path, pid: str, schema: list[dict] | None = None) -> None:
    """Build a minimal post-migration project on disk so tests can focus on prompt I/O."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "test",
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": None,
    })
    atomic_write_json(prompt_path(workspace, pid, "pr_baseline"), {
        "prompt_id": "pr_baseline",
        "label": "Baseline",
        "schema": schema or [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })


async def test_read_prompt_by_id(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ])
    pv = await read_prompt(workspace, pid, "pr_baseline")
    assert pv.prompt_id == "pr_baseline"
    assert len(pv.schema) == 1
    assert pv.schema[0].name == "invoice_no"


async def test_read_prompt_missing_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await read_prompt(workspace, pid, "pr_does_not_exist")


async def test_read_active_prompt_resolves_via_project_json(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid, schema=[
        {"name": "total", "type": "number", "description": "d", "required": False}
    ])
    pv = await read_active_prompt(workspace, pid)
    assert pv.prompt_id == "pr_baseline"
    assert pv.schema[0].name == "total"


async def test_write_prompt_to_active_when_prompt_id_none(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    new_schema = [SchemaField(name="supplier", type=FieldType.STRING, description="supplier name")]
    returned_pid = await write_prompt(
        workspace, pid,
        prompt_id=None,
        schema=new_schema,
        global_notes="some notes",
    )
    assert returned_pid == "pr_baseline"
    # On disk:
    blob = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert blob["schema"][0]["name"] == "supplier"
    assert blob["global_notes"] == "some notes"
    assert "updated_at" in blob


async def test_write_prompt_preserves_derived_from_and_created_at(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # First, manually set a derived_from + created_at on the existing prompt
    pp = prompt_path(workspace, pid, "pr_baseline")
    blob = json.loads(pp.read_text())
    blob["derived_from"] = "pr_parent"
    blob["created_at"] = "2026-01-01T00:00:00+00:00"
    atomic_write_json(pp, blob)

    await write_prompt(
        workspace, pid,
        prompt_id="pr_baseline",
        schema=[SchemaField(name="x", type=FieldType.STRING, description="d")],
        global_notes="",
    )
    after = json.loads(pp.read_text())
    assert after["derived_from"] == "pr_parent"
    assert after["created_at"] == "2026-01-01T00:00:00+00:00"
    # but updated_at changed
    assert after["updated_at"] != "2026-01-01T00:00:00+00:00"


async def test_write_prompt_to_nonexistent_raises(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    with pytest.raises(PromptNotFoundError):
        await write_prompt(
            workspace, pid,
            prompt_id="pr_nope",
            schema=[],
            global_notes="",
        )


async def test_list_prompts_marks_active(workspace: Path) -> None:
    pid = "p_test12345678"
    _seed_active_project(workspace, pid)
    # add a second prompt manually
    atomic_write_json(prompt_path(workspace, pid, "pr_other"), {
        "prompt_id": "pr_other",
        "label": "Other",
        "schema": [],
        "global_notes": "",
        "derived_from": None,
        "created_at": _now(),
        "updated_at": _now(),
    })
    items = await list_prompts(workspace, pid)
    by_id = {p["prompt_id"]: p for p in items}
    assert by_id["pr_baseline"]["is_active"] is True
    assert by_id["pr_other"]["is_active"] is False
    assert len(items) == 2
