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
