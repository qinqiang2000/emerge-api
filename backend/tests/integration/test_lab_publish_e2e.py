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


async def _seed_for_publish(workspace, pid: str) -> None:
    await write_schema(
        workspace, pid,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
        ],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, pid) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]})


@pytest.mark.asyncio
async def test_full_publish_then_extract(workspace, monkeypatch) -> None:
    pid = await create_project(workspace, name="p")
    await _seed_for_publish(workspace, pid)
    v = await freeze_version(workspace, pid)
    assert v == {"version_id": "v1"}
    issued = await issue_api_key(workspace, pid)

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Pepsi", "total_amount": 200.0}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )

    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": issued["key_plaintext"]},
        files={"file": ("inv.pdf", b"%PDF-1.4 sample", "application/pdf")},
    )
    assert r.status_code == 200
    assert r.json()["entities"] == [{"buyer_name": "Pepsi", "total_amount": 200.0}]


@pytest.mark.asyncio
async def test_case2_v2_publish_with_added_field(workspace, monkeypatch) -> None:
    pid = await create_project(workspace, name="p")
    await _seed_for_publish(workspace, pid)
    await freeze_version(workspace, pid)
    issued = await issue_api_key(workspace, pid)

    await write_schema(
        workspace, pid,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
            SchemaField(name="supplier_brn", type=FieldType.STRING,
                        description="12-digit BRN; new format only"),
        ],
        reason="case2 client feedback", allow_structural=True,
    )
    for i in range(3):
        did = f"d_{i:012d}"
        atomic_write_json(reviewed_dir(workspace, pid) / f"{did}.json", {
            "entities": [{"buyer_name": "ACME", "total_amount": 100.0,
                          "supplier_brn": "123456789012"}],
            "source": "manual",
        })
        atomic_write_json(predictions_draft_dir(workspace, pid) / f"{did}.json", {
            "entities": [{"buyer_name": "ACME", "total_amount": 100.0,
                          "supplier_brn": "123456789012"}],
        })
    v2 = await freeze_version(workspace, pid)
    assert v2 == {"version_id": "v2"}

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Pepsi", "total_amount": 200.0,
                                "supplier_brn": "987654321098"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )

    client = TestClient(app)
    r = client.post(
        f"/v1/{pid}/extract",
        headers={"X-API-Key": issued["key_plaintext"]},
        files={"file": ("inv.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["entities"][0]["supplier_brn"] == "987654321098"
