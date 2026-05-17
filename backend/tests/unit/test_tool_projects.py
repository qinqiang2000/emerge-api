import json
from pathlib import Path

import pytest

from app.tools.projects import (
    create_project,
    list_projects,
    rename_project,
    update_project,
)


async def test_create_project_writes_project_json(workspace: Path) -> None:
    out = await create_project(workspace, name="inv-MY")
    slug = out["slug"]
    pdir = workspace / slug
    assert pdir.is_dir()
    blob = json.loads((pdir / "project.json").read_text())
    assert blob["name"] == "inv-MY"
    assert blob["project_type"] == "extraction"
    assert blob["active_version_id"] is None
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"
    # pid is the immutable chat-event anchor; slug is folder + handle.
    assert blob["project_id"] == out["project_id"]
    assert blob["slug"] == slug
    assert blob["published_ids"] == []
    # Pro labeler slot seeded; None when EMERGE_DEFAULT_LABELER_MODEL unset.
    assert "labeler_model" in blob
    assert blob["labeler_model"] is None


async def test_create_project_writes_active_prompt_and_model(workspace: Path) -> None:
    """Post-M9.1: create_project writes prompts/pr_baseline.json (empty schema)
    + models/m_default.json + sets project.json active pointers. schema.json
    is NOT written for fresh projects (it has retired)."""
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    pdir = workspace / slug

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
    out = await create_project(workspace, name="x")
    items = await list_projects(workspace)
    assert len(items) == 1
    assert items[0]["slug"] == out["slug"]
    assert items[0]["project_id"] == out["project_id"]
    assert items[0]["name"] == "x"


async def test_update_project_extract_model(workspace: Path) -> None:
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    await update_project(workspace, slug, {"extract_model": "gpt-4o-2024-08"})
    blob = json.loads((workspace / slug / "project.json").read_text())
    assert blob["extract_model"] == "gpt-4o-2024-08"


async def test_rename_project_sets_name(workspace: Path) -> None:
    out = await create_project(workspace, name="Untitled-251205-093012")
    slug = out["slug"]
    res = await rename_project(workspace, slug, name="马来_振兴")
    new_slug = res["slug"]
    blob = json.loads((workspace / new_slug / "project.json").read_text())
    assert blob["name"] == "马来_振兴"
    # active pointers untouched.
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"


async def test_rename_project_strips_whitespace(workspace: Path) -> None:
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    res = await rename_project(workspace, slug, name="  trimmed  ")
    new_slug = res["slug"]
    blob = json.loads((workspace / new_slug / "project.json").read_text())
    assert blob["name"] == "trimmed"


async def test_rename_project_rejects_empty(workspace: Path) -> None:
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    with pytest.raises(ValueError, match="non-empty"):
        await rename_project(workspace, slug, name="   ")


async def test_rename_project_missing_slug_raises(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await rename_project(workspace, "doesnotexist", name="x")
