"""HTTP coverage for the M11 Phase B T10 lab routes:

* `POST /lab/projects/{slug}/extract` — wraps `extract_one`
* `POST /lab/projects/{slug}/extract/batch` — wraps `extract_batch`
* `POST /lab/projects/{slug}/score` — wraps `score`
* `GET  /lab/projects/{slug}/readiness` — wraps `readiness_check`
* `GET  /lab/projects/{slug}/contract-diff` — wraps `contract_diff`

Each test exercises a single route end-to-end against the FastAPI app —
no in-process plumbing. The provider factory is stubbed via monkeypatch
so the tests run synchronously without an external LLM call. The lab
routes are intentionally distinct from the prod fast-path
`POST /v1/extract` (which lives in publish.py) — these tests do not touch
that route; `test_v1_extract.py` covers it.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.provider.base import Provider, ProviderResult
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.publish import freeze_version
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    predictions_draft_dir,
    prediction_draft_path,
    reviewed_dir,
)


# A tiny but valid PNG payload — enough that `upload_doc`'s magic-byte
# sniff accepts it and `extract_one`'s `_doc_to_block` can stream it.
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x08\x00\x00\x00\x08"
    b"\x08\x06\x00\x00\x00\xc4\x0f\xbe\x8b\x00\x00\x00\x0cIDATx\x9cc\xf8"
    b"\xcf\xc0\x00\x00\x00\x03\x00\x01]Z9o\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _stub_provider(payload: dict) -> AsyncMock:
    p = AsyncMock(spec=Provider)
    p.extract.return_value = ProviderResult(
        raw_json=payload, model_id="stub", input_tokens=0, output_tokens=0,
    )
    return p


def _patch_provider(monkeypatch, stub: AsyncMock) -> None:
    """Stub both factory entry points: `extract_one` lazy-imports
    `app.provider.get_provider_for_model`, but route handlers may also
    have a module-level binding. Patching the source name catches both."""
    monkeypatch.setattr(
        "app.provider.get_provider_for_model",
        lambda *_a, **_k: stub,
    )


async def _seed_basic_project(workspace: Path, name: str = "p") -> str:
    """Mint a project with one string field — minimum viable for extract."""
    slug = (await create_project(workspace, name=name))["slug"]
    await write_schema(
        workspace, slug,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="Invoice number")],
        reason="seed", allow_structural=True,
    )
    return slug


async def _seed_doc(workspace: Path, slug: str, filename: str = "sample.png") -> str:
    meta = await upload_doc(workspace, slug, _PNG_BYTES, filename)
    return meta["filename"]


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/extract  (extract_one)
# ---------------------------------------------------------------------------


async def test_extract_one_happy_path(workspace: Path, monkeypatch) -> None:
    """Stub provider → 200 with the same payload the tool returns, plus
    `predictions/_draft/{filename}.json` lands on disk (extract_one's
    documented side effect)."""
    slug = await _seed_basic_project(workspace)
    filename = await _seed_doc(workspace, slug)
    stub = _stub_provider({"entities": [{"invoice_no": "INV-1"}]})
    _patch_provider(monkeypatch, stub)

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/extract", json={"filename": filename},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entities"] == [{"invoice_no": "INV-1"}]
    # Side effect on disk — same path the tool wrapper writes to.
    pp = prediction_draft_path(workspace, slug, filename)
    assert pp.exists()
    stub.extract.assert_awaited_once()


def test_extract_one_404_on_unknown_slug() -> None:
    """Slug-shaped but nonexistent → structured 404 envelope."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/does-not-exist/extract",
        json={"filename": "x.pdf"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["error_code"] == "project_not_found"


async def test_extract_one_400_on_prompt_override(workspace: Path) -> None:
    """`prompt_id` is reserved for future use; passing it should 400
    rather than silently ignoring (matches the route docstring contract)."""
    slug = await _seed_basic_project(workspace)
    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/extract",
        json={"filename": "x.pdf", "prompt_id": "pr_anything"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error_code"] == "prompt_override_unsupported"


async def test_extract_one_422_on_missing_filename(workspace: Path) -> None:
    """Missing required body field → pydantic 422."""
    slug = await _seed_basic_project(workspace)
    client = TestClient(app)
    r = client.post(f"/lab/projects/{slug}/extract", json={})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/extract/batch  (extract_batch)
# ---------------------------------------------------------------------------


async def test_extract_batch_sync_for_small_input(
    workspace: Path, monkeypatch,
) -> None:
    """≤8 filenames → returns the full batch summary inline. No job_id."""
    slug = await _seed_basic_project(workspace)
    filenames = [await _seed_doc(workspace, slug, f"d{i}.png") for i in range(3)]
    stub = _stub_provider({"entities": [{"invoice_no": "INV-X"}]})
    _patch_provider(monkeypatch, stub)

    client = TestClient(app)
    r = client.post(
        f"/lab/projects/{slug}/extract/batch", json={"filenames": filenames},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Sync shape mirrors `extract_batch` return: aggregate counts + per-doc.
    assert "job_id" not in body
    assert body["ok_count"] == 3
    assert body["err_count"] == 0
    assert set(body["per_doc"].keys()) == set(filenames)
    for fn in filenames:
        assert body["per_doc"][fn]["ok"] is True


async def test_extract_batch_async_for_large_input(
    workspace: Path, monkeypatch,
) -> None:
    """>8 filenames → returns `{job_id, status}` and the actual work
    happens on a background task. Polling the status route eventually
    reports `done` with the same per-doc shape the sync path produces.

    Uses ``httpx.AsyncClient`` + ``ASGITransport`` instead of ``TestClient``
    because ``TestClient`` spins up (and tears down) an event loop per
    request — orphaned ``asyncio.create_task`` calls never get to run.
    Same single-loop the async test runs in keeps the batch task alive.
    """
    slug = await _seed_basic_project(workspace)
    filenames = [await _seed_doc(workspace, slug, f"d{i}.png") for i in range(9)]
    stub = _stub_provider({"entities": [{"invoice_no": "INV-X"}]})
    _patch_provider(monkeypatch, stub)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post(
            f"/lab/projects/{slug}/extract/batch",
            json={"filenames": filenames},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        job_id = body.get("job_id")
        assert isinstance(job_id, str) and job_id.startswith("j_")
        assert body["status"] == "running"

        # Pump the loop until the background task finishes (50 * 0.05s = 2.5s).
        final = None
        for _ in range(50):
            s = await client.get(f"/lab/projects/{slug}/extract/batch/{job_id}")
            assert s.status_code == 200
            final = s.json()
            if final["status"] != "running":
                break
            await asyncio.sleep(0.05)
        assert final is not None and final["status"] == "done", final
        assert final["result"]["ok_count"] == 9


async def test_extract_batch_status_404_unknown_job(workspace: Path) -> None:
    """Unknown job_id → structured 404 envelope."""
    slug = await _seed_basic_project(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/extract/batch/j_doesnotexist0")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "job_not_found"


async def test_extract_batch_404_on_unknown_slug() -> None:
    """Slug doesn't exist → 404 before any provider work begins."""
    client = TestClient(app)
    r = client.post(
        "/lab/projects/does-not-exist/extract/batch",
        json={"filenames": ["a.pdf"]},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"


# ---------------------------------------------------------------------------
# POST /lab/projects/{slug}/score  (score)
# ---------------------------------------------------------------------------


async def _seed_for_score(workspace: Path) -> str:
    """Mint a project with one reviewed doc + matching draft prediction."""
    slug = await _seed_basic_project(workspace, name="score")
    meta = await upload_doc(workspace, slug, _PNG_BYTES, "sample.png")
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(workspace, slug) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1"}]},
    )
    await save_reviewed(
        workspace, slug, filename,
        entities=[{"invoice_no": "INV-1"}], source=ReviewedSource.MANUAL,
    )
    return slug


async def test_score_returns_perfect_when_pred_eq_reviewed(workspace: Path) -> None:
    """Reviewed and prediction identical → macro_f1 == 1.0."""
    slug = await _seed_for_score(workspace)
    client = TestClient(app)
    r = client.post(f"/lab/projects/{slug}/score")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["macro_f1"] == 1.0
    assert body["n_reviewed"] == 1
    assert isinstance(body["per_field"], list)


def test_score_404_on_unknown_project() -> None:
    """Slug-shaped value that doesn't exist → structured 404 envelope."""
    client = TestClient(app)
    r = client.post("/lab/projects/does-not-exist/score")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"


async def test_score_404_on_missing_schema(workspace: Path) -> None:
    """Project exists but has no schema → structured 404 (mirrors
    `/eval`'s validation order)."""
    out = await create_project(workspace, name="empty")
    slug = out["slug"]
    client = TestClient(app)
    r = client.post(f"/lab/projects/{slug}/score")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "schema_not_found"


# ---------------------------------------------------------------------------
# GET /lab/projects/{slug}/readiness  (readiness_check)
# ---------------------------------------------------------------------------


async def _seed_ready_to_publish(workspace: Path) -> str:
    """3 reviewed + matching predictions + a non-trivial schema → hard_pass."""
    slug = (await create_project(workspace, name="ready"))["slug"]
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
    return slug


async def test_readiness_returns_checklist_when_ready(workspace: Path) -> None:
    """Happy path: 3 matching docs → `hard_pass: True` and all hard
    checks pass."""
    slug = await _seed_ready_to_publish(workspace)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/readiness")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hard_pass"] is True
    assert body["n_reviewed"] == 3
    assert body["macro_f1"] == 1.0
    assert all(check["status"] == "pass" for check in body["checks"])


async def test_readiness_fails_when_under_threshold(workspace: Path) -> None:
    """Fewer than 3 reviewed → `reviewed_and_f1` check fails →
    hard_pass=False (so the body still 200s, but the caller sees the
    failing checks)."""
    slug = (await create_project(workspace, name="thin"))["slug"]
    await write_schema(
        workspace, slug,
        [SchemaField(name="x", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["hard_pass"] is False
    keys = {c["key"]: c for c in body["checks"]}
    assert keys["reviewed_and_f1"]["status"] == "fail"


def test_readiness_404_on_unknown_project() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/does-not-exist/readiness")
    assert r.status_code == 404
    assert r.json()["error_code"] == "project_not_found"


# ---------------------------------------------------------------------------
# GET /lab/projects/{slug}/contract-diff  (contract_diff)
# ---------------------------------------------------------------------------


async def test_contract_diff_no_prior_version(workspace: Path) -> None:
    """First publish: no `active_version_id` → diff vs an empty schema,
    `note` carries the "no prior active version" hint."""
    slug = (await create_project(workspace, name="firstpub"))["slug"]
    await write_schema(
        workspace, slug,
        [SchemaField(name="invoice_no", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/contract-diff")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == ["invoice_no"]
    assert body["removed"] == []
    assert body["is_breaking"] is False
    assert body.get("note") == "no prior active version"


async def test_contract_diff_explicit_from_to(workspace: Path) -> None:
    """Freeze v1, edit the lab schema, freeze v2, then diff `from=v1&to=v2`
    → `added` reflects the new field; `is_breaking=false` for additive."""
    slug = await _seed_ready_to_publish(workspace)
    v1 = await freeze_version(workspace, slug)
    assert v1["version_id"] == "v1"
    # Add another field and re-seed reviewed/predictions to keep readiness green.
    await write_schema(
        workspace, slug,
        [
            SchemaField(name="buyer_name", type=FieldType.STRING, description="x"),
            SchemaField(name="total", type=FieldType.NUMBER, description="x"),
        ],
        reason="add", allow_structural=True,
    )
    for i in range(3):
        did = f"doc{i}.pdf"
        atomic_write_json(reviewed_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total": 1.0}], "source": "manual"})
        atomic_write_json(predictions_draft_dir(workspace, slug) / f"{did}.json",
                          {"entities": [{"buyer_name": "ACME", "total": 1.0}]})
    v2 = await freeze_version(workspace, slug)
    assert v2["version_id"] == "v2"

    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/contract-diff?from=v1&to=v2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == ["total"]
    assert body["removed"] == []
    assert body["is_breaking"] is False


async def test_contract_diff_404_on_unknown_version(workspace: Path) -> None:
    """`from` references a version that doesn't exist → 404 envelope."""
    slug = (await create_project(workspace, name="x"))["slug"]
    await write_schema(
        workspace, slug,
        [SchemaField(name="x", type=FieldType.STRING, description="x")],
        reason="seed", allow_structural=True,
    )
    client = TestClient(app)
    r = client.get(f"/lab/projects/{slug}/contract-diff?from=v42")
    assert r.status_code == 404
    assert r.json()["error_code"] == "version_not_found"


def test_contract_diff_404_on_unknown_project() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/does-not-exist/contract-diff")
    assert r.status_code == 404
    assert r.json()["error_code"] == "project_not_found"
