"""HTTP coverage for `POST /lab/projects/{slug}/schema` and
`POST /lab/projects/{slug}/schema/derive` (M11 Phase B T8).

Both routes are thin wrappers over the tool module functions
(`write_schema`, `derive_schema`) — these tests pin the wire contract and
the validation gates without re-asserting the underlying tool semantics
(those are exercised by `tests/unit/test_tool_schema.py`).

For `derive_schema` we stub the provider with `respx` is overkill; instead
we patch the provider factory and the active-model read so the route runs
synchronously without an LLM call.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.provider.base import ProviderResult
from app.tools.docs import upload_doc
from app.tools.projects import create_project


# ── write_schema route ─────────────────────────────────────────────────


async def test_write_schema_route_persists_via_module_function(workspace: Path) -> None:
    """Happy path: POST a SchemaField list → 200 `{ok: true}`, and the
    follow-up GET surfaces the same fields. Round-trip confirms we are
    delegating to the same `write_schema` codepath the tool uses."""
    slug = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    body = {
        "schema": [
            {"name": "invoice_no", "type": "string", "description": "Invoice number"},
            {"name": "total", "type": "number", "description": "Total amount"},
        ],
        "reason": "seed via HTTP",
        "allow_structural": True,
    }
    r = client.post(f"/lab/projects/{slug}/schema", json=body)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Round-trip via the existing GET — same fields land back.
    g = client.get(f"/lab/projects/{slug}/schema")
    assert g.status_code == 200, g.text
    names = [f["name"] for f in g.json()]
    assert names == ["invoice_no", "total"]


async def test_write_schema_route_400_on_invalid_field(workspace: Path) -> None:
    """A field with no description (SchemaField requires it) → 400 with a
    structured envelope. The wrapper's pydantic re-validation catches it
    before the tool function ever runs."""
    slug = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/schema",
        json={
            "schema": [{"name": "invoice_no", "type": "string"}],  # missing description
            "reason": "bad shape",
            "allow_structural": True,
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == "invalid_schema"


async def test_write_schema_route_blocks_structural_without_flag(workspace: Path) -> None:
    """Adding a field without `allow_structural=true` → 400. Mirrors the
    `StructuralChangeError` gate the tool layer enforces."""
    slug = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    # Seed with one field
    r = client.post(
        f"/lab/projects/{slug}/schema",
        json={
            "schema": [{"name": "a", "type": "string", "description": "d"}],
            "reason": "init",
            "allow_structural": True,
        },
    )
    assert r.status_code == 200, r.text
    # Now try to add another without the flag.
    r = client.post(
        f"/lab/projects/{slug}/schema",
        json={
            "schema": [
                {"name": "a", "type": "string", "description": "d"},
                {"name": "b", "type": "string", "description": "d"},
            ],
            "reason": "add b",
            "allow_structural": False,
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == "structural_change_blocked"


# ── derive_schema route ────────────────────────────────────────────────


def _provider_with(fields: list[dict[str, Any]]) -> AsyncMock:
    """Return an AsyncMock provider whose `extract` yields a deterministic
    `{fields: [...]}` envelope — same shape `derive_schema` expects."""
    p = AsyncMock()
    p.extract = AsyncMock(
        return_value=ProviderResult(
            raw_json={"fields": fields},
            model_id="stub-model",
            input_tokens=0,
            output_tokens=0,
        )
    )
    return p


async def test_derive_schema_route_returns_proposed_fields(workspace: Path) -> None:
    """Happy path: POST sample filenames + intent → 200 with
    `{fields: [...], fields_proposed: N}` matching what the provider returns."""
    slug = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = (Path(__file__).parent.parent / "fixtures" / "invoice_sample.pdf").read_bytes()
    meta = await upload_doc(workspace, slug, pdf_bytes, "a.pdf")

    stub = _provider_with([
        {"name": "invoice_no", "type": "string", "description": "Invoice number", "required": True},
        {"name": "total", "type": "number", "description": "Total amount"},
    ])
    # The route imports `get_provider_for_model` lazily inside the handler
    # (kept lazy because the import pulls in provider adapters that read
    # API keys from env). Patching the source module is the most direct way
    # to intercept the call without depending on import order.
    with patch("app.provider.get_provider_for_model", return_value=stub):
        client = TestClient(app)
        r = client.post(
            f"/lab/projects/{slug}/schema/derive",
            json={"sample_filenames": [meta["filename"]], "intent": "extract invoice info"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields_proposed"] == 2
    names = [f["name"] for f in body["fields"]]
    assert names == ["invoice_no", "total"]
    stub.extract.assert_awaited_once()


def test_derive_schema_route_404_on_unknown_slug() -> None:
    """A slug-shaped value that doesn't exist → 404 — the existence check
    fires before the provider call (no work wasted)."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/does-not-exist/schema/derive",
        json={"sample_filenames": ["a.pdf"], "intent": "x"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "project_not_found"


async def test_derive_schema_route_422_on_missing_required_body(workspace: Path) -> None:
    """Missing `intent` → pydantic 422. Validation happens at the route
    layer before any project work begins."""
    slug = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/schema/derive",
        json={"sample_filenames": ["a.pdf"]},  # missing intent
    )
    assert r.status_code == 422, r.text
