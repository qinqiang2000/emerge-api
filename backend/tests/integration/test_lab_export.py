import io
import re
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.publish import freeze_version
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir, reviewed_dir


async def _seed_published(workspace: Path) -> str:
    pid = await create_project(workspace, name="us-invoice")
    await write_schema(
        workspace, pid,
        [SchemaField(name="invoice_number", type=FieldType.STRING, description="Invoice no")],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(
            reviewed_dir(workspace, pid) / f"{did}.json",
            {"entities": [{"invoice_number": "X"}], "source": "manual"},
        )
        atomic_write_json(
            predictions_draft_dir(workspace, pid) / f"{did}.json",
            {"entities": [{"invoice_number": "X"}]},
        )
    await freeze_version(workspace, pid)
    return pid


@pytest.mark.asyncio
async def test_export_active_version_default(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] in ("application/zip", "application/zip; charset=utf-8")
    cd = r.headers.get("content-disposition", "")
    assert "us-invoice" in cd and "v1" in cd
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "README.md" in z.namelist()


@pytest.mark.asyncio
async def test_export_explicit_version(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export?version=1")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_export_missing_version_404(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export?version=99")
    assert r.status_code == 404
    assert r.json()["error_code"] == "version_not_found"


@pytest.mark.asyncio
async def test_export_unpublished_project_404(workspace: Path) -> None:
    pid = await create_project(workspace, name="unpubd")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_published"


def test_export_invalid_pid_400() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/notapid/export")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_export_zip_contains_no_real_key(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    full_text = "\n".join(z.read(n).decode("utf-8") for n in z.namelist())
    assert re.search(r"ek_[A-Za-z0-9_-]{32}", full_text) is None
