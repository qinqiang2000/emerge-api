"""Freeze double-write + published_id audit coverage.

`freeze_version` is the seam between lab editing (mutable `prompts/`, `models/`)
and the public extract endpoint (immutable `_published/<pub>.json`). Each
call writes BOTH:
  * `versions/v{n}.json` — lab lineage, lives inside the project folder.
  * `_published/{pub_xxx}.json` — workspace-level frozen artifact (self-
    contained schema + model + params), `chmod 0o444` so it survives project
    rename/delete and emerge can hand it to a separate prod deployment.

`project.json.published_ids` is appended in time order so the publish UI can
show "current" + history without re-scanning `_published/`."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.prompt import write_prompt
from app.tools.publish import (
    PublishNotReadyError,
    freeze_version,
    issue_api_key,
)
from app.tools.reviewed import save_reviewed
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    keys_path,
    predictions_draft_dir,
    project_json_path,
    published_path,
    version_path,
)


async def _seed_ready_project(workspace: Path) -> str:
    """Create a project with enough seeded state for readiness checks to
    pass (or `force=True` to bypass). Returns the slug."""
    out = await create_project(workspace, name="us-invoice")
    slug = out["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    meta = await upload_doc(workspace, slug, pdf_bytes, "a.pdf")
    fname = meta["filename"]
    await write_prompt(
        workspace, slug,
        prompt_id=None,
        schema=[
            SchemaField(
                name="invoice_no", type=FieldType.STRING,
                description="d", required=True,
            ),
        ],
    )
    # Seed enough reviewed + prediction pairs for readiness to pass.
    for i in range(3):
        did = f"doc{i}.pdf"
        # First doc shares the real upload's filename; the others are stubs.
        target_name = fname if i == 0 else did
        atomic_write_json(
            predictions_draft_dir(workspace, slug) / f"{target_name}.json",
            {"entities": [{"invoice_no": f"X-{i}"}]},
        )
        await save_reviewed(
            workspace, slug, target_name,
            entities=[{"invoice_no": f"X-{i}"}],
            source=ReviewedSource.MANUAL,
        )
    return slug


# ----- freeze double-write -----------------------------------------------


@pytest.mark.asyncio
async def test_freeze_writes_both_artifacts(workspace: Path) -> None:
    slug = await _seed_ready_project(workspace)
    out = await freeze_version(workspace, slug, force=True)
    assert out["version_id"] == "v1"
    pub_id = out["published_id"]
    assert pub_id.startswith("pub_")

    # Lab-side immutable version
    vp = version_path(workspace, slug, 1)
    assert vp.exists()
    assert stat.S_IMODE(os.stat(vp).st_mode) == 0o444
    v_blob = json.loads(vp.read_text(encoding="utf-8"))

    # Workspace-level frozen artifact
    pp = published_path(workspace, pub_id)
    assert pp.exists()
    assert stat.S_IMODE(os.stat(pp).st_mode) == 0o444
    p_blob = json.loads(pp.read_text(encoding="utf-8"))

    # Same schema / model / params show up in both — the public extract
    # endpoint can serve the artifact without touching the lab folder.
    assert p_blob["published_id"] == pub_id
    assert p_blob["source_project_slug"] == slug
    assert p_blob["source_version_id"] == "v1"
    assert p_blob["schema"] == v_blob["schema"]
    assert p_blob["model_id"] == v_blob["model_id"]
    assert p_blob["params"] == v_blob["params"]
    assert p_blob["global_notes"] == v_blob["global_notes"]
    # source_project_id is the immutable pid for audit. Should match the
    # value persisted in project.json.
    proj = json.loads(project_json_path(workspace, slug).read_text(encoding="utf-8"))
    assert p_blob["source_project_id"] == proj["project_id"]


@pytest.mark.asyncio
async def test_publish_ids_append(workspace: Path) -> None:
    """Successive freezes append to `project.json.published_ids` in order."""
    slug = await _seed_ready_project(workspace)
    out1 = await freeze_version(workspace, slug, force=True)
    out2 = await freeze_version(workspace, slug, force=True)

    assert out1["published_id"] != out2["published_id"]
    proj = json.loads(project_json_path(workspace, slug).read_text(encoding="utf-8"))
    assert proj["published_ids"] == [out1["published_id"], out2["published_id"]]
    # The latest version_id is the second freeze.
    assert proj["active_version_id"] == out2["version_id"] == "v2"
    # Both frozen artifacts exist + immutable.
    for pub in (out1["published_id"], out2["published_id"]):
        pp = published_path(workspace, pub)
        assert pp.exists()
        assert stat.S_IMODE(os.stat(pp).st_mode) == 0o444


@pytest.mark.asyncio
async def test_freeze_skips_when_not_ready(workspace: Path) -> None:
    """`force=False` with failing readiness raises PublishNotReadyError, and
    nothing is written (no orphan v{n}.json / pub_*.json)."""
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    with pytest.raises(PublishNotReadyError) as exc:
        await freeze_version(workspace, slug, force=False)
    assert exc.value.error_code == "not_ready"
    # No v1.json
    assert not version_path(workspace, slug, 1).exists()
    # No _published/* files
    from app.workspace.paths import published_dir
    pub_root = published_dir(workspace)
    if pub_root.exists():
        assert list(pub_root.iterdir()) == []


@pytest.mark.asyncio
async def test_freeze_force_bypasses_readiness(workspace: Path) -> None:
    out = await create_project(workspace, name="x")
    slug = out["slug"]
    res = await freeze_version(workspace, slug, force=True)
    assert res["version_id"] == "v1"
    assert res["published_id"].startswith("pub_")
    # Both artifacts written even though readiness would have failed.
    assert version_path(workspace, slug, 1).exists()
    assert published_path(workspace, res["published_id"]).exists()


@pytest.mark.asyncio
async def test_issue_api_key_user_scope(workspace: Path) -> None:
    """Minted keys are stored under `user_id`, not `project_id`. One key per
    `(user_id, scope)` after rotation."""
    issued = await issue_api_key()
    blob = json.loads(keys_path(workspace).read_text(encoding="utf-8"))
    assert len(blob) == 1
    row = blob[0]
    assert row["user_id"] == "default"
    assert row["scope"] == "extract"
    assert "project_id" not in row
    assert row["hash"] == issued["key_hash"]
