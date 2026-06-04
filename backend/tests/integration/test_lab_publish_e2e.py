"""End-to-end publish + extract flows on the new slug + published_id contract.

freeze_version returns `{version_id, published_id}`; the public extract
endpoint takes `published_id` as a form field and `X-API-Key` as a header.
"""
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


async def _seed_for_publish(workspace, slug: str) -> None:
    await write_schema(
        workspace, slug,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
        ],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(reviewed_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total_amount": 100.0}]})


@pytest.mark.asyncio
async def test_full_publish_then_extract(workspace, monkeypatch) -> None:
    slug = (await create_project(workspace, name="p"))["slug"]
    await _seed_for_publish(workspace, slug)
    frozen = await freeze_version(workspace, slug)
    assert frozen["version_id"] == "v1"
    pub_id = frozen["published_id"]
    assert pub_id.startswith("pub_")
    issued = await issue_api_key(user_id="default")

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Pepsi", "total_amount": 200.0}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id, **_kw: fake_provider,
    )

    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": issued["key_plaintext"]},
        data={"published_id": pub_id},
        files={"file": ("inv.pdf", b"%PDF-1.4 sample", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["entities"] == [{"buyer_name": "Pepsi", "total_amount": 200.0}]


@pytest.mark.asyncio
async def test_case2_v2_publish_with_added_field(workspace, monkeypatch) -> None:
    slug = (await create_project(workspace, name="p"))["slug"]
    await _seed_for_publish(workspace, slug)
    await freeze_version(workspace, slug)
    issued = await issue_api_key(user_id="default")

    await write_schema(
        workspace, slug,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total_amount", type=FieldType.NUMBER, description="x"),
            SchemaField(name="supplier_brn", type=FieldType.STRING,
                        description="12-digit BRN; new format only"),
        ],
        reason="case2 client feedback", allow_structural=True,
    )
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(reviewed_dir(workspace, slug) / f"{did}.json", {
            "entities": [{"buyer_name": "ACME", "total_amount": 100.0,
                          "supplier_brn": "123456789012"}],
            "source": "manual",
        })
        atomic_write_json(predictions_draft_dir(workspace, slug) / f"{did}.json", {
            "entities": [{"buyer_name": "ACME", "total_amount": 100.0,
                          "supplier_brn": "123456789012"}],
        })
    frozen_v2 = await freeze_version(workspace, slug)
    assert frozen_v2["version_id"] == "v2"
    pub_v2 = frozen_v2["published_id"]
    assert pub_v2.startswith("pub_")

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Pepsi", "total_amount": 200.0,
                                "supplier_brn": "987654321098"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id, **_kw: fake_provider,
    )

    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": issued["key_plaintext"]},
        data={"published_id": pub_v2},
        files={"file": ("inv.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entities"][0]["supplier_brn"] == "987654321098"
