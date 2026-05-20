from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.reviewed import ReviewedSource
from app.schemas.schema_field import FieldType, SchemaField
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.reviewed import save_reviewed
from app.tools.schema import write_schema
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    metrics_dir,
    predictions_draft_dir,
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    monkeypatch.chdir(tmp_path)
    return TestClient(app)


def _seed_project_with_reviewed(ws: Path) -> str:
    """Create a project with schema + 1 reviewed doc + 1 matching prediction.
    Returns the slug."""
    schema = [
        SchemaField(name="invoice_no", type=FieldType.STRING, description="d"),
        SchemaField(name="total", type=FieldType.NUMBER, description="d"),
    ]
    slug = asyncio.run(create_project(ws, name="eval-routes"))["slug"]
    asyncio.run(write_schema(ws, slug, schema, reason="t", allow_structural=True))
    meta = asyncio.run(upload_doc(ws, slug, b"\x89PNG\r\n\x1a\nstub", "x.png"))
    filename = meta["filename"]
    atomic_write_json(
        predictions_draft_dir(ws, slug) / f"{filename}.json",
        {"entities": [{"invoice_no": "INV-1", "total": 100}]},
    )
    asyncio.run(save_reviewed(
        ws, slug, filename,
        entities=[{"invoice_no": "INV-1", "total": 100}],
        source=ReviewedSource.MANUAL,
    ))
    return slug


def test_post_eval_creates_dir(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    r = client.post(f"/lab/projects/{slug}/eval", json={"use_llm_judge": False})
    assert r.status_code == 200
    blob = r.json()
    # M12.x: field_accuracy_macro is the new headline; macro_f1 is None.
    assert blob["field_accuracy_macro"] == 1.0
    assert blob["macro_f1"] is None
    assert blob["doc_accuracy"] == 1.0
    ts = blob["ts"]
    md = metrics_dir(tmp_path, slug)
    target = md / f"eval_{ts}"
    assert target.is_dir()
    assert (target / "summary.json").exists()
    assert (target / "cells.jsonl").exists()
    assert (target / "matrix.csv").exists()
    assert (target / "meta.json").exists()


def test_list_evals_returns_current_dir(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    r1 = client.post(f"/lab/projects/{slug}/eval")
    assert r1.status_code == 200
    r2 = client.get(f"/lab/projects/{slug}/evals")
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert rows[0]["doc_accuracy"] == 1.0
    assert rows[0]["field_accuracy_macro"] == 1.0


def test_get_summary_jsonl_matrix(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    r1 = client.post(f"/lab/projects/{slug}/eval")
    ts = r1.json()["ts"]

    rs = client.get(f"/lab/projects/{slug}/eval/{ts}/summary.json")
    assert rs.status_code == 200
    assert rs.json()["field_accuracy_macro"] == 1.0

    rc = client.get(f"/lab/projects/{slug}/eval/{ts}/cells.jsonl")
    assert rc.status_code == 200
    lines = rc.text.splitlines()
    assert len(lines) == 2  # 1 doc × 2 fields

    rm = client.get(f"/lab/projects/{slug}/eval/{ts}/matrix.csv")
    assert rm.status_code == 200
    assert 'attachment; filename="eval_' in rm.headers["content-disposition"]
    assert "filename" in rm.text.splitlines()[0]


def test_eval_latest_dir_form(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    client.post(f"/lab/projects/{slug}/eval")
    r = client.get(f"/lab/projects/{slug}/evals/latest")
    assert r.status_code == 200
    assert r.json()["field_accuracy_macro"] == 1.0


def test_eval_latest_legacy_only(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    md = metrics_dir(tmp_path, slug)
    md.mkdir(parents=True, exist_ok=True)
    legacy_blob = {
        "n_docs": 1,
        "n_reviewed": 1,
        "macro_f1": 0.75,
        "per_field": [],
        "errors": [],
        "ts": "2024-01-01T00-00-00Z",
        "schema_field_count": 0,
    }
    (md / "eval_2024-01-01T00-00-00Z.json").write_text(json.dumps(legacy_blob))
    r = client.get(f"/lab/projects/{slug}/evals/latest")
    assert r.status_code == 200
    assert r.json()["macro_f1"] == 0.75
    # doc_accuracy is optional/None in the legacy form
    assert r.json().get("doc_accuracy") is None


def test_invalid_ts_returns_400(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    # Bare invalid identifier — not URL-encoded slash, just bad ts shape.
    r = client.get(f"/lab/projects/{slug}/eval/garbage-ts/summary.json")
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "invalid_ts"


def test_legacy_summary_via_ts(client: TestClient, tmp_path: Path) -> None:
    slug = _seed_project_with_reviewed(tmp_path)
    md = metrics_dir(tmp_path, slug)
    md.mkdir(parents=True, exist_ok=True)
    legacy_blob = {
        "n_docs": 1,
        "n_reviewed": 1,
        "macro_f1": 0.66,
        "per_field": [],
        "errors": [],
        "ts": "2024-01-01T00-00-00Z",
        "schema_field_count": 0,
    }
    (md / "eval_2024-01-01T00-00-00Z.json").write_text(json.dumps(legacy_blob))
    r = client.get(
        f"/lab/projects/{slug}/eval/2024-01-01T00-00-00Z/summary.json"
    )
    assert r.status_code == 200
    assert r.json()["macro_f1"] == 0.66
