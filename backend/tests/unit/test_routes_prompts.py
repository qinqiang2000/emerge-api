from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def test_list_prompts_returns_active_marker(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.prompt import create_prompt as _create_prompt

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    asyncio.run(_create_prompt(tmp_path, pid, label="trial"))

    r = client.get(f"/lab/projects/{pid}/prompts")
    assert r.status_code == 200
    rows = r.json()
    by_label = {row["label"]: row for row in rows}
    assert by_label["Baseline"]["is_active"] is True
    assert by_label["trial"]["is_active"] is False


def test_get_active_prompt_returns_full_blob_with_derived_from(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.prompt import create_prompt as _create_prompt, switch_active_prompt as _switch

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    new_id = asyncio.run(_create_prompt(tmp_path, pid, label="trial"))
    asyncio.run(_switch(tmp_path, pid, new_id))

    r = client.get(f"/lab/projects/{pid}/prompts/active")
    assert r.status_code == 200
    blob = r.json()
    assert blob["prompt_id"] == new_id
    assert blob["label"] == "trial"
    assert blob["derived_from"] == "pr_baseline"
    assert "schema" in blob
    assert "global_notes" in blob


def test_get_prompt_by_id(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.get(f"/lab/projects/{pid}/prompts/pr_baseline")
    assert r.status_code == 200
    blob = r.json()
    assert blob["prompt_id"] == "pr_baseline"


def test_get_prompt_missing_404(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.get(f"/lab/projects/{pid}/prompts/pr_nope")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "prompt_not_found"


def test_put_active_prompt_writes_schema(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    body = {
        "schema": [
            {"name": "vendor_name", "type": "string", "description": "vendor", "required": True},
            {"name": "total", "type": "number", "description": "total amount"},
        ],
        "global_notes": "edited inline",
    }
    r = client.put(f"/lab/projects/{pid}/prompts/active", json=body)
    assert r.status_code == 200, r.text
    blob = r.json()
    names = [f["name"] for f in blob["schema"]]
    assert names == ["vendor_name", "total"]
    assert blob["global_notes"] == "edited inline"

    # Verify it persisted: a fresh GET returns the same shape.
    r2 = client.get(f"/lab/projects/{pid}/prompts/active")
    assert r2.status_code == 200
    assert [f["name"] for f in r2.json()["schema"]] == ["vendor_name", "total"]


def test_put_active_prompt_rejects_invalid_snake_case(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.put(
        f"/lab/projects/{pid}/prompts/active",
        json={"schema": [{"name": "BadCamel", "type": "string", "description": "x"}]},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error_code"] == "invalid_schema_field"


def test_put_active_prompt_allows_empty_schema_wipe(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    # Seed a non-empty schema first so the wipe path is meaningful.
    client.put(
        f"/lab/projects/{pid}/prompts/active",
        json={"schema": [{"name": "x", "type": "string", "description": "x"}]},
    )
    r = client.put(f"/lab/projects/{pid}/prompts/active", json={"schema": []})
    assert r.status_code == 200
    assert r.json()["schema"] == []


def test_list_prompts_legacy_project_migrates_first(client: TestClient, tmp_path: Path) -> None:
    pid = "p_legacyhttp02"
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
        "extract_model": "gemini-2.5-flash",
        "extract_params": {"temperature": 0.0},
        "active_version_id": None,
    }))
    (pdir / "schema.json").write_text(json.dumps([
        {"name": "x", "type": "string", "description": "d", "required": False},
    ]))

    r = client.get(f"/lab/projects/{pid}/prompts")
    assert r.status_code == 200
    assert (pdir / "prompts" / "pr_baseline.json").exists()
