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


def _seed_src(workspace: Path, src_slug: str) -> None:
    """A migrated source project: project.json + 2 prompts + 2 models +
    one stray subdir that should NOT be copied."""
    pdir = workspace / src_slug
    pdir.mkdir(parents=True, exist_ok=True)
    prompts_dir(workspace, src_slug).mkdir(parents=True, exist_ok=True)
    models_dir(workspace, src_slug).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, src_slug).mkdir(parents=True, exist_ok=True)
    (pdir / "chats").mkdir(exist_ok=True)
    (pdir / "predictions" / "_draft").mkdir(parents=True, exist_ok=True)
    (pdir / "reviewed").mkdir(exist_ok=True)
    (pdir / "experiments" / "ex_foo").mkdir(parents=True, exist_ok=True)
    (pdir / "versions").mkdir(exist_ok=True)
    (pdir / "metrics").mkdir(exist_ok=True)

    atomic_write_json(project_json_path(workspace, src_slug), {
        "project_id": "p_src1234567a",
        "slug": src_slug,
        "name": "us-invoice",
        "project_type": "extraction",
        "created_at": _now(),
        "active_prompt_id": "pr_baseline",
        "active_model_id": "m_default",
        "active_version_id": "v3",
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
        "published_ids": ["pub_legacyabc123"],
    })
    for pid_name in ("pr_baseline", "pr_variant"):
        atomic_write_json(prompt_path(workspace, src_slug, pid_name), {
            "prompt_id": pid_name,
            "label": f"L({pid_name})",
            "schema": [],
            "global_notes": "src notes",
            "derived_from": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    for mid_name in ("m_default", "m_alt"):
        atomic_write_json(model_path(workspace, src_slug, mid_name), {
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
    src_slug = "us-invoice"
    _seed_src(workspace, src_slug)

    out = await fork_project(workspace, src_slug=src_slug, name="uk-invoice")
    new_slug = out["slug"]
    new_pid = out["project_id"]

    # New pid + slug are fresh
    assert new_pid.startswith("p_")
    assert new_slug != src_slug
    new_dir = project_dir(workspace, new_slug)

    # Whitelist: project.json + prompts/ + models/
    new_blob = json.loads(project_json_path(workspace, new_slug).read_text())
    assert new_blob["name"] == "uk-invoice"
    assert new_blob["slug"] == new_slug
    assert new_blob["project_id"] == new_pid
    assert new_blob["active_version_id"] is None
    # Fork starts with empty publish lineage — frozen artifacts don't
    # inherit, that's the whole point of `published_id` decoupling.
    assert new_blob["published_ids"] == []
    assert new_blob["active_prompt_id"] == "pr_baseline"
    assert new_blob["active_model_id"] == "m_default"
    assert "created_at" in new_blob

    assert prompt_path(workspace, new_slug, "pr_baseline").exists()
    assert prompt_path(workspace, new_slug, "pr_variant").exists()
    assert model_path(workspace, new_slug, "m_default").exists()
    assert model_path(workspace, new_slug, "m_alt").exists()

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
    """include_docs=True hardlinks both the file and the sidecar in `.meta/`.

    Post-d_xxx: layout is `docs/<filename>` + `docs/.meta/<filename>.json`.
    Skipping the sidecar would orphan the doc (list_docs filters on sidecar
    presence)."""
    from app.workspace.paths import docs_meta_dir
    src_slug = "us-invoice"
    _seed_src(workspace, src_slug)
    # Seed one doc + its sidecar at the new layout.
    src_docs = docs_dir(workspace, src_slug)
    (src_docs / "a.pdf").write_bytes(b"PDFCONTENT")
    src_meta = docs_meta_dir(workspace, src_slug)
    src_meta.mkdir(parents=True, exist_ok=True)
    (src_meta / "a.pdf.json").write_text('{"filename": "a.pdf", "ext": "pdf"}')

    out = await fork_project(
        workspace, src_slug=src_slug, name="uk-invoice", include_docs=True,
    )
    new_slug = out["slug"]

    new_docs = docs_dir(workspace, new_slug)
    assert (new_docs / "a.pdf").read_bytes() == b"PDFCONTENT"
    assert json.loads((new_docs / ".meta" / "a.pdf.json").read_text())["filename"] == "a.pdf"


async def test_fork_default_skips_docs(workspace: Path) -> None:
    src_slug = "us-invoice"
    _seed_src(workspace, src_slug)
    (docs_dir(workspace, src_slug) / "a.pdf").write_bytes(b"X")

    out = await fork_project(workspace, src_slug=src_slug, name="uk-invoice")
    # The fork creates an empty docs/ but skips the bytes when include_docs=False.
    new_docs = docs_dir(workspace, out["slug"])
    # `iterdir()` may include the `.meta/` subdir if it ever got materialized;
    # the key assertion is that the real doc file wasn't cloned.
    assert not (new_docs / "a.pdf").exists()


async def test_fork_missing_src_raises(workspace: Path) -> None:
    from app.tools.fork import ForkSourceNotFoundError
    with pytest.raises(ForkSourceNotFoundError):
        await fork_project(workspace, src_slug="doesnotexist", name="x")
