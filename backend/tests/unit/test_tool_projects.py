import json
from pathlib import Path

from app.tools.projects import (
    create_project,
    list_projects,
    update_project,
)


async def test_create_project_writes_project_json(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    pdir = workspace / pid
    assert pdir.is_dir()
    blob = json.loads((pdir / "project.json").read_text())
    assert blob["name"] == "inv-MY"
    assert blob["project_type"] == "extraction"
    assert blob["active_version_id"] is None


async def test_create_project_writes_empty_schema(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    blob = json.loads((workspace / pid / "schema.json").read_text())
    assert blob == []


async def test_list_projects_empty(workspace: Path) -> None:
    assert await list_projects(workspace) == []


async def test_list_projects_after_create(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    items = await list_projects(workspace)
    assert len(items) == 1
    assert items[0]["project_id"] == pid
    assert items[0]["name"] == "x"


async def test_update_project_extract_model(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    await update_project(workspace, pid, {"extract_model": "gpt-4o-2024-08"})
    blob = json.loads((workspace / pid / "project.json").read_text())
    assert blob["extract_model"] == "gpt-4o-2024-08"
