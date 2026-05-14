import io
import json
import re
import zipfile
from pathlib import Path

import pytest

from app.exports.bundler import BundleVersionMissingError, build_zip_bundle
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.publish import freeze_version
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir, reviewed_dir


async def _seed_published(workspace: Path) -> str:
    pid = (await create_project(workspace, name="us-invoice"))["slug"]
    await write_schema(
        workspace, pid,
        [
            SchemaField(name="invoice_number", type=FieldType.STRING, description="Invoice no"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="Total"),
        ],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(
            reviewed_dir(workspace, pid) / f"{did}.json",
            {"entities": [{"invoice_number": "INV-1", "total_amount": 1.0}], "source": "manual"},
        )
        atomic_write_json(
            predictions_draft_dir(workspace, pid) / f"{did}.json",
            {"entities": [{"invoice_number": "INV-1", "total_amount": 1.0}]},
        )
    await freeze_version(workspace, pid)
    return pid


@pytest.mark.asyncio
async def test_bundle_contains_expected_members(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    blob = build_zip_bundle(workspace=workspace, project_id=pid, version_n=1)
    z = zipfile.ZipFile(io.BytesIO(blob))
    assert set(z.namelist()) == {"schema.json", "version.json", "curl_example.sh", "README.md"}


@pytest.mark.asyncio
async def test_bundle_version_json_matches_frozen(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    blob = build_zip_bundle(workspace=workspace, project_id=pid, version_n=1)
    z = zipfile.ZipFile(io.BytesIO(blob))
    v = json.loads(z.read("version.json").decode("utf-8"))
    assert v["version_id"] == "v1"
    assert {f["name"] for f in v["schema"]} == {"invoice_number", "total_amount"}


@pytest.mark.asyncio
async def test_bundle_curl_uses_placeholder_key(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    blob = build_zip_bundle(workspace=workspace, project_id=pid, version_n=1)
    z = zipfile.ZipFile(io.BytesIO(blob))
    curl = z.read("curl_example.sh").decode("utf-8")
    assert "<your saved key>" in curl
    assert "ek_" not in curl
    assert pid in curl
    assert "/v1/" in curl


@pytest.mark.asyncio
async def test_bundle_readme_no_real_key_pattern(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    blob = build_zip_bundle(workspace=workspace, project_id=pid, version_n=1)
    z = zipfile.ZipFile(io.BytesIO(blob))
    readme = z.read("README.md").decode("utf-8")
    assert re.search(r"ek_[A-Za-z0-9_-]{32}", readme) is None


@pytest.mark.asyncio
async def test_bundle_missing_version_raises(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    with pytest.raises(BundleVersionMissingError):
        build_zip_bundle(workspace=workspace, project_id=pid, version_n=99)
