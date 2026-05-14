import json
import os
from pathlib import Path

import pytest

from app.tools.publish import (
    PublishNotReadyError,
    freeze_version,
)
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    docs_dir,
    predictions_draft_dir,
    project_dir,
    project_json_path,
    reviewed_dir,
    schema_path,
    version_path,
    versions_dir,
)


def _ready_project(workspace: Path, slug: str) -> None:
    """Seed a slug-folder project ready for freeze_version (post-rewrite).

    Uses the legacy `schema.json` so the migrate-on-read path still kicks in
    and produces a `pr_baseline` prompt with the same schema — that's the
    code path agent-2 must keep working until agent-3 wires routes."""
    project_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    versions_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, slug), {
        "project_id": "p_abc123def456",
        "slug": slug,
        "name": "p", "project_type": "extraction", "created_at": "x",
        "extract_model": "claude-sonnet-4-6",
        "extract_params": {"temperature": 0.0},
        "autoresearch_proposer_model": None,
        "active_version_id": None,
        "publish_min_macro_f1": 0.7,
        "published_ids": [],
    })
    atomic_write_json(schema_path(workspace, slug), [
        {"name": "buyer_name", "type": "string", "description": "x", "required": False},
        {"name": "total_amount", "type": "number", "description": "x", "required": False},
    ])
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]})


@pytest.mark.asyncio
async def test_freeze_writes_v1_immutable(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    out = await freeze_version(tmp_path, slug)
    assert out["version_id"] == "v1"
    assert out["published_id"].startswith("pub_")
    target = version_path(tmp_path, slug, 1)
    assert target.exists()
    blob = json.loads(target.read_text())
    assert blob["version_id"] == "v1"
    assert blob["schema"][0]["name"] == "buyer_name"
    assert blob["model_id"] == "claude-sonnet-4-6"
    mode = os.stat(target).st_mode & 0o777
    assert mode == 0o444


@pytest.mark.asyncio
async def test_freeze_updates_active_version_id(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    await freeze_version(tmp_path, slug)
    project = json.loads(project_json_path(tmp_path, slug).read_text())
    assert project["active_version_id"] == "v1"


@pytest.mark.asyncio
async def test_freeze_v2_increments(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    await freeze_version(tmp_path, slug)
    # Update via the prompt variant (post-migration the schema lives there;
    # writing the legacy schema.json would be a no-op since prompts/ already
    # exists and migrate is gated).
    from app.workspace.paths import prompt_path
    prompt = json.loads(prompt_path(tmp_path, slug, "pr_baseline").read_text())
    prompt["schema"] = [
        {"name": "buyer_name", "type": "string", "description": "x", "required": False},
        {"name": "total_amount", "type": "number", "description": "x", "required": False},
        {"name": "supplier_brn", "type": "string", "description": "x", "required": False},
    ]
    atomic_write_json(prompt_path(tmp_path, slug, "pr_baseline"), prompt)
    out2 = await freeze_version(tmp_path, slug)
    assert out2["version_id"] == "v2"
    assert out2["published_id"].startswith("pub_")
    project = json.loads(project_json_path(tmp_path, slug).read_text())
    assert project["active_version_id"] == "v2"
    v1 = version_path(tmp_path, slug, 1)
    assert v1.exists()
    assert os.stat(v1).st_mode & 0o777 == 0o444


@pytest.mark.asyncio
async def test_freeze_without_readiness_raises(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    atomic_write_json(schema_path(tmp_path, slug), [])
    with pytest.raises(PublishNotReadyError) as exc:
        await freeze_version(tmp_path, slug)
    assert exc.value.error_code == "not_ready"


@pytest.mark.asyncio
async def test_freeze_force_bypasses_readiness(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    atomic_write_json(schema_path(tmp_path, slug), [])
    out = await freeze_version(tmp_path, slug, force=True)
    assert out["version_id"] == "v1"


@pytest.mark.asyncio
async def test_freeze_includes_global_notes(tmp_path: Path) -> None:
    slug = "us-invoice"
    _ready_project(tmp_path, slug)
    (project_dir(tmp_path, slug) / "global_notes.md").write_text("Read carefully.")
    await freeze_version(tmp_path, slug)
    blob = json.loads(version_path(tmp_path, slug, 1).read_text())
    assert blob["global_notes"] == "Read carefully."


async def test_freeze_version_writes_derived_from_audit_field(
    workspace: Path,
) -> None:
    """The frozen version blob records which active prompt/model it was derived from."""
    from app.tools.projects import create_project
    from app.tools.publish import freeze_version
    from app.tools.reviewed import save_reviewed
    from app.tools.docs import upload_doc
    from app.tools.prompt import write_prompt
    from app.schemas.reviewed import ReviewedSource
    from app.schemas.schema_field import FieldType, SchemaField
    from app.workspace.paths import predictions_draft_dir, version_path
    from app.workspace.atomic import atomic_write_json as _aw

    proj = await create_project(workspace, name="x")
    slug = proj["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    meta = await upload_doc(workspace, slug, pdf_bytes, "a.pdf")
    fname = meta["filename"]
    await write_prompt(
        workspace, slug,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d", required=True)],
    )
    # Seed reviewed + prediction so readiness passes with force=True
    _aw(predictions_draft_dir(workspace, slug) / f"{fname}.json",
        {"entities": [{"invoice_no": "X-1"}]})
    await save_reviewed(
        workspace, slug, fname,
        entities=[{"invoice_no": "X-1"}],
        source=ReviewedSource.MANUAL,
    )

    out = await freeze_version(workspace, slug, force=True)
    n = int(out["version_id"][1:])
    v_blob = json.loads(version_path(workspace, slug, n).read_text())
    assert v_blob["derived_from"]["prompt_id"] == "pr_baseline"
    assert v_blob["derived_from"]["model_id"] == "m_default"
    assert v_blob["derived_from"]["experiment_id"] is None
    assert v_blob["version_id"] == out["version_id"]
    assert v_blob["model_id"]  # provider_model_id from m_default
    assert "schema" in v_blob
    assert "global_notes" in v_blob
