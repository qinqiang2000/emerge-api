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
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"


async def test_create_project_writes_active_prompt_and_model(workspace: Path) -> None:
    """Post-M9.1: create_project writes prompts/pr_baseline.json (empty schema)
    + models/m_default.json + sets project.json active pointers. schema.json
    is NOT written for fresh projects (it has retired)."""
    pid = await create_project(workspace, name="x")
    pdir = workspace / pid

    pp = pdir / "prompts" / "pr_baseline.json"
    mp = pdir / "models" / "m_default.json"
    assert pp.exists()
    assert mp.exists()

    pv = json.loads(pp.read_text())
    assert pv["prompt_id"] == "pr_baseline"
    assert pv["schema"] == []
    assert pv["global_notes"] == ""

    mc = json.loads(mp.read_text())
    assert mc["model_id"] == "m_default"

    project = json.loads((pdir / "project.json").read_text())
    assert project["active_prompt_id"] == "pr_baseline"
    assert project["active_model_id"] == "m_default"

    # schema.json is NOT written for new projects (retired)
    assert not (pdir / "schema.json").exists()


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
