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
    import json as _json
    (pdir / "project.json").write_text(_json.dumps({
        "name": "test",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }))
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
    # round-trippable: endpoint now serializes via SchemaField.model_dump so optional
    # fields (enum, children) are included as None; check only core keys.
    parsed = json.loads(body)
    assert len(parsed) == len(fields)
    for actual, expected in zip(parsed, fields):
        for k, v in expected.items():
            assert actual[k] == v


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


def test_get_project_schema_reads_from_active_prompt(client: TestClient, tmp_path: Path) -> None:
    """After M9.1, GET /lab/projects/{pid}/schema reads from prompts/{active}.json."""
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.prompt import write_prompt as _write_prompt
    from app.schemas.schema_field import FieldType, SchemaField

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    asyncio.run(_write_prompt(
        tmp_path, pid,
        prompt_id=None,
        schema=[SchemaField(name="invoice_no", type=FieldType.STRING, description="d")],
    ))
    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["name"] == "invoice_no"


def test_legacy_project_migrates_on_first_http_read(client: TestClient, tmp_path: Path) -> None:
    """A legacy project on disk migrates the first time its schema is read via HTTP."""
    pid = "p_legacyhttp01"
    pdir = tmp_path / pid
    pdir.mkdir(parents=True)
    (pdir / "docs").mkdir()
    (pdir / "predictions" / "_draft").mkdir(parents=True)
    (pdir / "versions").mkdir()
    (pdir / "chats").mkdir()
    (pdir / "project.json").write_text(json.dumps({
        "name": "legacy",
        "project_type": "extraction",
        "created_at": "2026-05-01T00:00:00+00:00",
        "extract_model": "gemini-2.0-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }))
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "invoice_no", "type": "string", "description": "d", "required": False}
    ]))

    r = client.get(f"/lab/projects/{pid}/schema")
    assert r.status_code == 200
    # After this call, the prompts/ + models/ layout exists
    assert (pdir / "prompts" / "pr_baseline.json").exists()
    assert (pdir / "models" / "m_default.json").exists()


def test_version_raw_shape_fields_remaps_schema_key(client: TestClient, tmp_path: Path) -> None:
    """publish.py writes the frozen blob with key `schema` (see publish.py:331).
    The ?shape=fields contract (spec §3.3) names the list `fields`, so the
    endpoint remaps `schema` → `fields` and passes the rest through.
    """
    pid = "p_versionaa003"
    blob = {
        "version_id": "v6",
        "schema": [{"name": "x", "type": "string", "description": "x field"}],
        "model_id": "gemini-2.5-flash",
        "frozen_at": "2026-05-10T00:00:00+00:00",
    }
    _write_version(tmp_path, pid, 6, blob)

    resp = client.get(f"/lab/projects/{pid}/versions/v6/raw?shape=fields")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["fields"] == blob["schema"]
    assert "schema" not in payload  # remapped, not duplicated
    assert payload["frozen_at"] == blob["frozen_at"]
    assert payload["model_id"] == blob["model_id"]
    assert payload["version_id"] == "v6"
