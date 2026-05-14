"""End-to-end tests for the public extract endpoint.

Post slug-transparency the URL is stable: `POST /v1/extract` with
`published_id` as a form field and `X-API-Key` as a header. Keys are user-
scoped — one key calls *any* `published_id` (this is also exercised below).
"""
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
    published_path,
    reviewed_dir,
)


async def _ready_published_project(workspace: Path, *, name: str = "p") -> tuple[str, str, str]:
    """Build a project that's ready to freeze, freeze it, mint a key.

    Returns `(slug, published_id, key_plaintext)`.
    """
    out = await create_project(workspace, name=name)
    slug = out["slug"]
    await write_schema(
        workspace, slug,
        [SchemaField(name="buyer_name", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(reviewed_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME"}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME"}]})
    frozen = await freeze_version(workspace, slug)
    issued = await issue_api_key(workspace, user_id="default")
    return slug, frozen["published_id"], issued["key_plaintext"]


@pytest.mark.asyncio
async def test_v1_extract_happy(workspace: Path, monkeypatch) -> None:
    _slug, pub_id, key = await _ready_published_project(workspace)
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
        "/v1/extract",
        headers={"X-API-Key": key},
        data={"published_id": pub_id},
        files={"file": ("x.pdf", b"%PDF-1.4 dummy", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["entities"] == [{"buyer_name": "Coca-Cola"}]


@pytest.mark.asyncio
async def test_v1_extract_missing_key_401(workspace: Path) -> None:
    _slug, pub_id, _key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        data={"published_id": pub_id},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "missing_api_key"


@pytest.mark.asyncio
async def test_v1_extract_bad_key_401(workspace: Path) -> None:
    _slug, pub_id, _key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": "ek_completelyBogusValue000000000000"},
        data={"published_id": pub_id},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 401
    assert r.json()["error_code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_v1_extract_unknown_published_id_returns_404(workspace: Path) -> None:
    _slug, _pub_id, key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": key},
        data={"published_id": "pub_zzzzzzzzzzzz"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 404
    assert r.json()["error_code"] == "not_found"


@pytest.mark.asyncio
async def test_v1_extract_invalid_published_id_format_400(workspace: Path) -> None:
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": "ek_x"},
        data={"published_id": "notapub"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "invalid_published_id"


@pytest.mark.asyncio
async def test_v1_extract_unsupported_extension_400(workspace: Path) -> None:
    _slug, pub_id, key = await _ready_published_project(workspace)
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": key},
        data={"published_id": pub_id},
        files={"file": ("x.exe", b"badbinary", "application/octet-stream")},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "unsupported_file_type"


@pytest.mark.asyncio
async def test_v1_extract_does_not_read_schema_json(workspace: Path, monkeypatch) -> None:
    """The endpoint reads the self-contained frozen artifact, not the lab-side
    `schema.json`. Mutating `schema.json` after freeze must not change what
    the public API serves."""
    slug, pub_id, key = await _ready_published_project(workspace)
    from app.workspace.paths import schema_path
    atomic_write_json(schema_path(workspace, slug), [
        {"name": "totally_different", "type": "string", "description": "x", "required": False},
    ])
    fake_provider = AsyncMock(spec=Provider)
    captured: dict = {}

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
        "/v1/extract",
        headers={"X-API-Key": key},
        data={"published_id": pub_id},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 200
    fields = captured["response_schema"]["properties"]["entities"]["items"]["properties"]
    assert "buyer_name" in fields
    assert "totally_different" not in fields


@pytest.mark.asyncio
async def test_v1_extract_one_key_multiple_pubs(workspace: Path, monkeypatch) -> None:
    """A single user-scoped key calls any `published_id` — plan use-case 6.

    Freeze two unrelated projects, mint ONE key, and verify both pub_xxx URLs
    answer 200 with that same key. This is the "AI-native API symmetry"
    contract: keys are not project-scoped.
    """
    _slug_a, pub_a, key_a = await _ready_published_project(workspace, name="proj-a")
    # `issue_api_key` upserts per user — calling it a second time would
    # invalidate the first key. So instead freeze another project and keep
    # using `key_a`.
    out_b = await create_project(workspace, name="proj-b")
    slug_b = out_b["slug"]
    await write_schema(
        workspace, slug_b,
        [SchemaField(name="seller_name", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    reviewed_dir(workspace, slug_b).mkdir(parents=True, exist_ok=True)
    predictions_draft_dir(workspace, slug_b).mkdir(parents=True, exist_ok=True)
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(reviewed_dir(workspace, slug_b) / f"{did}.json",
                          {"entities": [{"seller_name": "Bob"}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, slug_b) / f"{did}.json",
                          {"entities": [{"seller_name": "Bob"}]})
    frozen_b = await freeze_version(workspace, slug_b)
    pub_b = frozen_b["published_id"]

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": []},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )
    client = TestClient(app)
    for pub in (pub_a, pub_b):
        r = client.post(
            "/v1/extract",
            headers={"X-API-Key": key_a},
            data={"published_id": pub},
            files={"file": ("x.pdf", b"%PDF", "application/pdf")},
        )
        assert r.status_code == 200, f"pub={pub} text={r.text}"


@pytest.mark.asyncio
async def test_v1_extract_survives_project_rename(workspace: Path, monkeypatch) -> None:
    """The frozen artifact is self-contained — renaming or deleting the
    source project after freeze must NOT break the public extract URL. This
    is the "emerge is staging" contract: `published_id` is portable.
    """
    from app.tools.projects import rename_project
    slug, pub_id, key = await _ready_published_project(workspace, name="orig-slug")
    # Sanity: the frozen artifact exists at the workspace level (outside the
    # project folder).
    assert published_path(workspace, pub_id).exists()

    await rename_project(workspace, slug, name="renamed-completely")

    fake_provider = AsyncMock(spec=Provider)
    fake_provider.extract.return_value = ProviderResult(
        raw_json={"entities": [{"buyer_name": "Still works"}]},
        model_id="claude-sonnet-4-6", input_tokens=0, output_tokens=0,
    )
    monkeypatch.setattr(
        "app.api.routes.publish.get_provider_for_model",
        lambda model_id: fake_provider,
    )
    client = TestClient(app)
    r = client.post(
        "/v1/extract",
        headers={"X-API-Key": key},
        data={"published_id": pub_id},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["entities"] == [{"buyer_name": "Still works"}]
