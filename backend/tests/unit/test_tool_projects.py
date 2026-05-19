import json
from pathlib import Path

import pytest

from app.tools.projects import (
    create_project,
    delete_project,
    list_projects,
    rename_project,
    update_project,
)
from app.workspace.pid_index import get_index


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


async def test_rename_project_slug_only_pulls_placeholder_name_along(
    workspace: Path,
) -> None:
    """Slug-only rename of a still-anonymous chat-mint project must also
    bump the auto `Chat-…` display name — otherwise the sidebar keeps
    showing the timestamp after the user has already named the slug."""
    out = await create_project(workspace, name="Chat-260519-071155")
    slug = out["slug"]
    res = await rename_project(workspace, slug, new_slug="荣耀_欧洲1")
    new_slug = res["slug"]
    blob = json.loads((workspace / new_slug / "project.json").read_text())
    assert blob["slug"] == new_slug
    assert blob["name"] == new_slug


async def test_rename_project_slug_only_preserves_user_name(workspace: Path) -> None:
    """A user-set name (anything that's not the auto placeholder) must be
    left alone on a slug-only rename — name and slug can legitimately
    diverge once the user has expressed intent."""
    out = await create_project(workspace, name="acme-invoices")
    slug = out["slug"]
    res = await rename_project(workspace, slug, new_slug="acme-v2")
    new_slug = res["slug"]
    blob = json.loads((workspace / new_slug / "project.json").read_text())
    assert blob["slug"] == new_slug
    assert blob["name"] == "acme-invoices"


async def test_delete_project_removes_dir_and_unregisters_pid(workspace: Path) -> None:
    out = await create_project(workspace, name="trash-me")
    slug = out["slug"]
    pid = out["project_id"]
    assert (workspace / slug).is_dir()
    assert get_index(workspace).resolve_pid(pid) == slug

    res = await delete_project(workspace, slug)

    assert res == {"deleted_slug": slug, "deleted_pid": pid}
    assert not (workspace / slug).exists()
    assert get_index(workspace).resolve_pid(pid) is None
    # Slug is free for reuse.
    re_out = await create_project(workspace, name="trash-me")
    assert re_out["slug"] == slug


async def test_delete_project_missing_slug_raises(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await delete_project(workspace, "doesnotexist")


async def test_list_projects_uses_folder_name_when_blob_slug_drifted(workspace: Path) -> None:
    """`Bash mv old new` (the SDK rename path the skill documents) renames the
    folder but doesn't touch `project.json.slug`. Folder name is the URL
    handle and the source of truth — the lab UI / agent must see the
    folder name, not the stale blob field. Regression: a prior `**blob`
    spread order leaked the stale slug back out of `list_projects`."""
    import os

    out = await create_project(workspace, name="old-name")
    old_slug = out["slug"]
    new_slug = "new-name"
    os.rename(workspace / old_slug, workspace / new_slug)
    # Blob still says slug=old_slug — that's the divergence we're guarding.

    items = await list_projects(workspace)
    assert len(items) == 1
    assert items[0]["slug"] == new_slug
    # `project_id` (the pid) is preserved from the blob.
    assert items[0]["project_id"] == out["project_id"]


async def test_list_projects_resyncs_blob_slug_on_read(workspace: Path) -> None:
    """Beyond surfacing the folder name through the list response, the lazy
    migration should heal the underlying `project.json.slug` so agents that
    `Read project.json` see a consistent view next turn."""
    import json as _json
    import os

    out = await create_project(workspace, name="old")
    old_slug = out["slug"]
    new_slug = "renamed"
    os.rename(workspace / old_slug, workspace / new_slug)

    # The blob is stale right after the bare mv.
    assert _json.loads((workspace / new_slug / "project.json").read_text())["slug"] == old_slug

    await list_projects(workspace)

    # Read entry-point ran the lazy migration → blob now matches the folder.
    assert _json.loads((workspace / new_slug / "project.json").read_text())["slug"] == new_slug


async def test_delete_project_tombstones_before_rmtree(workspace: Path) -> None:
    """Critical ordering: project.json must be unlinked *before* the parent
    rmtree, so any in-flight chat-log write (which gates on project.json
    presence) trips its tombstone check rather than resurrecting `chats/`.

    We can't observe the in-between state from a single-threaded test, so we
    end-to-end check the gate's contract: appending after delete is a no-op.
    """
    from app.chat.log import append_event

    out = await create_project(workspace, name="x")
    slug = out["slug"]
    await delete_project(workspace, slug)
    await append_event(workspace, slug, "c_trail", {"type": "agent_text", "text": "hi"})
    assert not (workspace / slug).exists()
