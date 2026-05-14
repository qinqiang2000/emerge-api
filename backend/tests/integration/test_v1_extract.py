from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.provider.base import Provider, ProviderResult
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.projects import create_project
from app.tools.publish import freeze_version, issue_api_key
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    predictions_draft_dir,
    reviewed_dir,
)


async def _ready_published_project(workspace: Path) -> tuple[str, str]:
    pid = (await create_project(workspace, name="p"))["slug"]
    await write_schema(
        workspace, pid,
        [SchemaField(name="buyer_name", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME"}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME"}]})
    await freeze_version(workspace, pid)
    issued = await issue_api_key(workspace, pid)
    return pid, issued["key_plaintext"]


@pytest.mark.asyncio
async def test_v1_extract_happy(workspace: Path, monkeypatch) -> None:
    pid, key = await _ready_published_project(workspace)
    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Coca-Cola"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )
    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": key},
        files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["entities"] == [{"buyer_name": "Coca-Cola"}]


@pytest.mark.asyncio
async def test_v1_extract_missing_key_401(workspace: Path) -> None:
    pid, _key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(f"/v1/{pid}/extract",
                    files={"file": ("x.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "missing_api_key"


@pytest.mark.asyncio
async def test_v1_extract_bad_key_401(workspace: Path) -> None:
    pid, _key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": "ek_completelyBogusValue000000000000"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 401
    assert r.json()["error_code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_v1_extract_pid_mismatch_returns_404(workspace: Path) -> None:
    _pid, key = await _ready_published_project(workspace)
    other_pid_valid = "p_zzzzzzzzzzzz"
    client = TestClient(app)
    r = client.post(
        f"/v1/{other_pid_valid}/extract",
        headers={"X-API-Key": key},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_found"


@pytest.mark.asyncio
async def test_v1_extract_unpublished_project_returns_404(workspace: Path) -> None:
    pid = (await create_project(workspace, name="p"))["slug"]
    issued = await issue_api_key(workspace, pid)
    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": issued["key_plaintext"]},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_published"


@pytest.mark.asyncio
async def test_v1_extract_invalid_pid_format_400(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/notapid/extract",
        headers={"X-API-Key": "ek_x"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_v1_extract_unsupported_extension_400(workspace: Path) -> None:
    pid, key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": key},
        files={"file": ("x.exe", b"badbinary", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "unsupported_file_type"


@pytest.mark.asyncio
async def test_v1_extract_does_not_read_schema_json(workspace: Path, monkeypatch) -> None:
    pid, key = await _ready_published_project(workspace)
    from app.workspace.paths import schema_path
    atomic_write_json(schema_path(workspace, pid), [
        {"name": "totally_different", "type": "string", "description": "x", "required": False},
    ])
    fake_provider = AsyncMock(spec=Provider)
    captured = {}

    async def _capture(**kwargs):
        captured["response_schema"] = kwargs["response_schema"]
        return ProviderResult(
            raw_json={"entities": []},
            model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
        )

    fake_provider.extract.side_effect = _capture
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )
    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": key},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 200
    fields = captured["response_schema"]["properties"]["entities"]["items"]["properties"]
    assert "buyer_name" in fields
    assert "totally_different" not in fields
