import io
import re
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.publish import freeze_version
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir, reviewed_dir


async def _seed_published(workspace: Path, name: str = "us-invoice") -> str:
    pid = (await create_project(workspace, name=name))["slug"]
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
    pid = (await create_project(workspace, name="unpubd"))["slug"]
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_published"


def test_export_unknown_slug_404() -> None:
    """A valid-shape slug that doesn't exist returns 404 (existence check)."""
    client = TestClient(app)
    r = client.get("/lab/projects/notapid/export")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_preserves_non_ascii_project_name(workspace: Path) -> None:
    """RFC 5987 `filename*` carries the real name through.

    Regression for the follow-up "export bundle filename for non-ASCII project
    names". Measured outputs of the old ASCII allowlist, on real prod names:
    `振兴_20260707` → `20260707-v1.zip`, `海信日本-627人工标注` → `627-v1.zip`, and
    any name with no ASCII at all (`发票云空间`) → `project-v1.zip`. Every one
    of them loses the part a human identifies the file by, and the last case
    makes two projects collide in one Downloads folder.
    """
    pid = await _seed_published(workspace, name="振兴_20260707")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]

    star = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert star, f"no RFC 5987 filename* in {cd!r}"
    assert unquote(star.group(1)) == "振兴_20260707-v1.zip"
    # ASCII fallback still present for pre-5987 clients, and still a legal
    # `quoted-string` (no bare `"` smuggled in from the project name).
    plain = re.search(r'filename="([^"]*)"', cd)
    assert plain and plain.group(1).isascii()


@pytest.mark.asyncio
async def test_export_filename_drops_path_separators(workspace: Path) -> None:
    """A `/` in a display name must not survive into the header.

    `name` is free text (only the folder `slug` is constrained), so a project
    called `a/b` could otherwise hand the browser a filename with a path
    separator in it.
    """
    pid = await _seed_published(workspace, name='pay/ments:"q"')
    client = TestClient(app)
    cd = client.get(f"/lab/projects/{pid}/export").headers["content-disposition"]
    star = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    assert star
    decoded = unquote(star.group(1))
    assert not (set(decoded) & set('/\\:*?"<>|'))
    assert decoded.endswith("-v1.zip")


@pytest.mark.asyncio
async def test_export_sends_content_length(workspace: Path) -> None:
    """Not chunked.

    The bundle is generated in memory and is kilobytes, so it ships as one
    `Response` with a real `Content-Length` — that is what gives the browser a
    size and a progress bar. `StreamingResponse(iter([blob]))` (the previous
    shape) cannot know the length and falls back to chunked transfer, buying no
    memory back in exchange.
    """
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    assert r.headers.get("content-length") == str(len(r.content))
    assert "chunked" not in r.headers.get("transfer-encoding", "")


@pytest.mark.asyncio
async def test_export_zip_contains_no_real_key(workspace: Path) -> None:
    pid = await _seed_published(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/export")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    full_text = "\n".join(z.read(n).decode("utf-8") for n in z.namelist())
    assert re.search(r"ek_[A-Za-z0-9_-]{32}", full_text) is None
