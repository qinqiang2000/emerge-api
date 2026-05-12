from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workspace.paths import schema_path


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def _write_schema(tmp_path: Path, pid: str, fields: list[dict]) -> None:
    pdir = tmp_path / pid
    pdir.mkdir(parents=True, exist_ok=True)
    schema_path(tmp_path, pid).write_text(json.dumps(fields))


def test_schema_raw_returns_pretty_printed_text(client: TestClient, tmp_path: Path) -> None:
    pid = "p_testaa00001a"
    fields = [
        {"name": "invoice_number", "type": "string", "description": "Invoice ID", "required": True},
        {"name": "total_amount", "type": "number", "description": "Total"},
    ]
    _write_schema(tmp_path, pid, fields)

    resp = client.get(f"/lab/projects/{pid}/schema/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    body = resp.text
    # pretty-printed: contains newlines + 2-space indent
    assert "\n" in body
    assert '  "name": "invoice_number"' in body
    # round-trippable
    assert json.loads(body) == fields


def test_schema_raw_returns_404_when_missing(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_noschema001a/schema/raw")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "schema_not_found"


def _write_version(tmp_path: Path, pid: str, n: int, blob: dict) -> None:
    vdir = tmp_path / pid / "versions"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"v{n}.json").write_text(json.dumps(blob))


def test_version_raw_returns_pretty_printed_text(client: TestClient, tmp_path: Path) -> None:
    pid = "p_versionaa001"
    blob = {
        "fields": [{"name": "x", "type": "string", "description": "x field"}],
        "frozen_at": "2026-05-10T00:00:00+00:00",
    }
    _write_version(tmp_path, pid, 6, blob)

    resp = client.get(f"/lab/projects/{pid}/versions/v6/raw")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert json.loads(resp.text) == blob


def test_version_raw_shape_fields_returns_json(client: TestClient, tmp_path: Path) -> None:
    pid = "p_versionaa002"
    blob = {
        "fields": [{"name": "x", "type": "string", "description": "x field"}],
        "frozen_at": "2026-05-10T00:00:00+00:00",
    }
    _write_version(tmp_path, pid, 6, blob)

    resp = client.get(f"/lab/projects/{pid}/versions/v6/raw?shape=fields")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert payload["fields"] == blob["fields"]
    assert payload["frozen_at"] == blob["frozen_at"]


def test_version_raw_returns_404_when_missing(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_versionaa099/versions/v99/raw")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "version_not_found"


def test_version_raw_rejects_malformed_version_id(client: TestClient) -> None:
    resp = client.get("/lab/projects/p_versionaa098/versions/notaversion/raw")
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "invalid_version_id"
