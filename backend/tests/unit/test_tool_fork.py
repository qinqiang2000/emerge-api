from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.fork import fork_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    model_path,
    models_dir,
    project_dir,
    project_json_path,
    prompt_path,
    prompts_dir,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_src(workspace: Path, src_pid: str) -> None:
    """A migrated source project: project.json + 2 prompts + 2 models +
    one stray subdir that should NOT be copied."""
    pdir = workspace / src_pid
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, src_pid).mkdir(parents=True, exist_ok=True)
    (pdir / "chats").mkdir(exist_ok=True)
    (pdir / "predictions" / "_draft").mkdir(parents=True, exist_ok=True)
    (pdir / "reviewed").mkdir(exist_ok=True)
    (pdir / "experiments" / "ex_foo").mkdir(parents=True, exist_ok=True)
    (pdir / "versions").mkdir(exist_ok=True)
    (pdir / "metrics").mkdir(exist_ok=True)

    atomic_write_json(project_json_path(workspace, src_pid), {
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v3",
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
    })
    for pid_name in ("pr_baseline", "pr_variant"):
        atomic_write_json(prompt_path(workspace, src_pid, pid_name), {
            "prompt_id": pid_name,
            "label": f"L({pid_name})",
            "schema": [],
            "global_notes": "src notes",
            "derived_from": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    for mid_name in ("m_default", "m_alt"):
        atomic_write_json(model_path(workspace, src_pid, mid_name), {
            "model_id": mid_name,
            "label": f"M({mid_name})",
            "provider": "google",
            "provider_model_id": "gemini-2.5-flash",
            "params": {"temperature": 0.0},
            "created_at": _now(),
        })
    # stray content that must NOT be copied
    (pdir / "chats" / "c_abc.jsonl").write_text("ignored")
    (pdir / "predictions" / "_draft" / "d_x.json").write_text("{}")
    (pdir / "reviewed" / "d_x.json").write_text("{}")
    (pdir / "experiments" / "ex_foo" / "meta.json").write_text("{}")
    (pdir / "versions" / "v3.json").write_text("{}")
    (pdir / "metrics" / "eval_1.json").write_text("{}")


async def test_fork_copies_prompts_models_rewrites_project_json(workspace: Path) -> None:
    src_pid = "p_src123456789"  # NOTE: doesn't match safe_project_id regex — that's fine for the tool unit; routes apply safety.
    _seed_src(workspace, src_pid)

    new_pid = await fork_project(workspace, src_pid=src_pid, name="uk-invoice")

    # New pid format
    assert new_pid.startswith("p_") and new_pid != src_pid
    new_dir = project_dir(workspace, new_pid)

    # Whitelist: project.json + prompts/ + models/
    new_blob = json.loads(project_json_path(workspace, new_pid).read_text())
    assert new_blob["name"] == "uk-invoice"
    assert new_blob["active_version_id"] is None
    assert new_blob["active_prompt_id"] == "pr_baseline"
    assert new_blob["active_model_id"] == "m_default"
    assert "created_at" in new_blob

    assert prompt_path(workspace, new_pid, "pr_baseline").exists()
    assert prompt_path(workspace, new_pid, "pr_variant").exists()
    assert model_path(workspace, new_pid, "m_default").exists()
    assert model_path(workspace, new_pid, "m_alt").exists()

    # Blacklist: nothing else copied
    assert not (new_dir / "chats").exists()
    assert not (new_dir / "predictions").exists()
    assert not (new_dir / "reviewed").exists()
    assert not (new_dir / "experiments").exists()
    assert not (new_dir / "versions").exists()
    assert not (new_dir / "metrics").exists()
    # docs/ is created (empty) for the new project even without include_docs
    assert (new_dir / "docs").exists()
    assert list((new_dir / "docs").iterdir()) == []


async def test_fork_include_docs_clones_doc_files(workspace: Path) -> None:
    src_pid = "p_src123456789"
    _seed_src(workspace, src_pid)
    # Seed two doc files
    src_docs = docs_dir(workspace, src_pid)
    (src_docs / "d_aaa.pdf").write_bytes(b"PDFCONTENT")
    (src_docs / "d_aaa.meta.json").write_text('{"original_filename": "a.pdf"}')

    new_pid = await fork_project(
        workspace, src_pid=src_pid, name="uk-invoice", include_docs=True,
    )

    new_docs = docs_dir(workspace, new_pid)
    assert (new_docs / "d_aaa.pdf").read_bytes() == b"PDFCONTENT"
    assert json.loads((new_docs / "d_aaa.meta.json").read_text())["original_filename"] == "a.pdf"


async def test_fork_default_skips_docs(workspace: Path) -> None:
    src_pid = "p_src123456789"
    _seed_src(workspace, src_pid)
    (docs_dir(workspace, src_pid) / "d_aaa.pdf").write_bytes(b"X")

    new_pid = await fork_project(workspace, src_pid=src_pid, name="uk-invoice")
    assert list(docs_dir(workspace, new_pid).iterdir()) == []


async def test_fork_missing_src_raises(workspace: Path) -> None:
    from app.tools.fork import ForkSourceNotFoundError
    with pytest.raises(ForkSourceNotFoundError):
        await fork_project(workspace, src_pid="p_doesnotexist", name="x")
