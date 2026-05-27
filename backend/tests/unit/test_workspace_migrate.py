from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.workspace.migrate import migrate_project_if_needed
from app.workspace.paths import (
    model_path,
    models_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
    schema_path,
)


def _build_legacy_project(workspace: Path, pid: str = "p_legacy00abcd") -> str:
    """Hand-build a pre-M9.1 layout on disk."""
    pdir = workspace / pid
    pdir.mkdir(parents=True, exist_ok=False)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "Legacy invoice",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }), encoding="utf-8")
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": False},
        {"name": "total", "type": "number", "description": "Total amount", "required": True},
    ]), encoding="utf-8")
    (pdir / "global_notes.md").write_text("This is a US invoice.\nUSD only.", encoding="utf-8")
    return pid


async def test_migrate_builds_prompts_and_models(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    pp = prompt_path(workspace, pid, "pr_baseline")
    assert pp.exists()
    pv = json.loads(pp.read_text())
    assert pv["prompt_id"] == "pr_baseline"
    assert pv["label"] == "Baseline"
    assert len(pv["schema"]) == 2
    assert pv["schema"][0]["name"] == "invoice_no"
    assert pv["global_notes"] == "This is a US invoice.\nUSD only."
    assert pv.get("derived_from") is None
    assert "created_at" in pv and "updated_at" in pv


async def test_migrate_builds_default_model(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    mp = model_path(workspace, pid, "m_default")
    assert mp.exists()
    mc = json.loads(mp.read_text())
    assert mc["model_id"] == "m_default"
    assert mc["provider"] == "google"
    assert mc["provider_model_id"] == "gemini-2.5-flash"
    assert mc["params"] == {"temperature": 0.0}


async def test_migrate_updates_project_json_active_pointers(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    blob = json.loads(project_json_path(workspace, pid).read_text())
    assert blob["active_prompt_id"] == "pr_baseline"
    assert blob["active_model_id"] == "m_default"
    # Legacy `extract_model` / `extract_params` fields are dropped post-migrate
    # — runtime extract reads `models/{active_model_id}.json` exclusively, so
    # leaving the redundant blob fields just confused agent `Read project.json`
    # output. See plan: env-var × model-axis design audit.
    assert "extract_model" not in blob
    assert "extract_params" not in blob


async def test_migrate_does_not_delete_legacy_files(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)

    # schema.json and global_notes.md linger on disk (cleanup deferred to later milestone)
    assert schema_path(workspace, pid).exists()
    assert (workspace / pid / "global_notes.md").exists()


async def test_migrate_idempotent_when_prompts_dir_exists(workspace: Path) -> None:
    pid = _build_legacy_project(workspace)
    await migrate_project_if_needed(workspace, pid)
    # Mutate the migrated prompt
    pp = prompt_path(workspace, pid, "pr_baseline")
    pv = json.loads(pp.read_text())
    pv["schema"][0]["description"] = "manually edited"
    pp.write_text(json.dumps(pv), encoding="utf-8")

    # Second migration must be a no-op
    await migrate_project_if_needed(workspace, pid)
    pv2 = json.loads(pp.read_text())
    assert pv2["schema"][0]["description"] == "manually edited"


async def test_migrate_handles_missing_global_notes(workspace: Path) -> None:
    """Legacy projects without global_notes.md still migrate, with empty notes."""
    pid = _build_legacy_project(workspace)
    (workspace / pid / "global_notes.md").unlink()
    await migrate_project_if_needed(workspace, pid)

    pv = json.loads(prompt_path(workspace, pid, "pr_baseline").read_text())
    assert pv["global_notes"] == ""


async def test_migrate_concurrent_safe(workspace: Path) -> None:
    """Two concurrent migrate calls on the same project must serialize via project_lock
    and produce exactly one set of new layout files (no torn writes, no double-mint)."""
    pid = _build_legacy_project(workspace)
    await asyncio.gather(
        migrate_project_if_needed(workspace, pid),
        migrate_project_if_needed(workspace, pid),
        migrate_project_if_needed(workspace, pid),
    )
    # One pr_baseline + one m_default
    pd = prompts_dir(workspace, pid)
    md = models_dir(workspace, pid)
    assert sorted(p.name for p in pd.iterdir() if p.is_file()) == ["pr_baseline.json"]
    assert sorted(p.name for p in md.iterdir() if p.is_file()) == ["m_default.json"]


async def test_migrate_noop_on_missing_project(workspace: Path) -> None:
    """If pid directory doesn't exist, migrate is a silent no-op (no crash)."""
    await migrate_project_if_needed(workspace, "p_does_not_exist00")
    # nothing to assert besides no exception


async def test_migrate_handles_no_extract_model(workspace: Path) -> None:
    """A degenerate legacy project.json without extract_model still produces a usable m_default."""
    pid = _build_legacy_project(workspace)
    pj = project_json_path(workspace, pid)
    blob = json.loads(pj.read_text())
    del blob["extract_model"]
    pj.write_text(json.dumps(blob), encoding="utf-8")

    await migrate_project_if_needed(workspace, pid)
    mc = json.loads(model_path(workspace, pid, "m_default").read_text())
    # Falls back to settings default
    assert mc["provider_model_id"]  # non-empty
