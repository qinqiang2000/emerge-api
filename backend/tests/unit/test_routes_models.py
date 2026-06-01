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


def test_list_models_returns_active_marker(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create
    from app.tools.model import create_model as _create_model

    # The seeded default model is keyed by the stable id `m_default`; its *label*
    # is the provider model id (e.g. "gemini-2.5-flash"), not the old engineering-
    # internal "Default" wording (rewritten by migrate._backfill_m_default_label),
    # so assert the active marker by model_id, not label.
    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    asyncio.run(_create_model(
        tmp_path, pid,
        label="Sonnet 4.6", provider="anthropic", provider_model_id="claude-sonnet-4-6",
    ))
    r = client.get(f"/lab/projects/{pid}/models")
    assert r.status_code == 200
    rows = r.json()
    by_id = {row["model_id"]: row for row in rows}
    assert by_id["m_default"]["is_active"] is True
    by_label = {row["label"]: row for row in rows}
    assert by_label["Sonnet 4.6"]["is_active"] is False


def test_get_active_model_returns_full_blob(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.config import get_settings
    from app.tools.projects import create_project as _create

    settings = get_settings()
    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.get(f"/lab/projects/{pid}/models/active")
    assert r.status_code == 200
    blob = r.json()
    assert blob["model_id"] == "m_default"
    assert blob["provider"] == "google"
    assert blob["provider_model_id"] == settings.default_extract_model


def test_get_model_by_id(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.get(f"/lab/projects/{pid}/models/m_default")
    assert r.status_code == 200
    blob = r.json()
    assert blob["model_id"] == "m_default"


def test_get_model_missing_404(client: TestClient, tmp_path: Path) -> None:
    import asyncio
    from app.tools.projects import create_project as _create

    pid = asyncio.run(_create(tmp_path, name="t"))["slug"]
    r = client.get(f"/lab/projects/{pid}/models/m_nope")
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "model_not_found"
