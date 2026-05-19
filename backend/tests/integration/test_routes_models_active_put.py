"""HTTP coverage of `PUT /lab/projects/{slug}/models/active`.

Mirror of the existing `PUT /lab/projects/{slug}/prompts/active` route
(see `tests/unit/test_routes_prompts.py::test_put_active_prompt_*`).
M11 §Phase B T9 — closes the symmetry gap where `switch_active_model`
was tool-only.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.model import create_model as _create_model
from app.tools.projects import create_project as _create


client = TestClient(app)


def test_put_active_model_switches_and_get_reflects(workspace: Path) -> None:
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    new_id = asyncio.run(_create_model(
        workspace, pid,
        label="Sonnet 4.6", provider="anthropic", provider_model_id="claude-sonnet-4-6",
    ))

    # Sanity: default model is active before the switch.
    before = client.get(f"/lab/projects/{pid}/models/active").json()
    assert before["model_id"] == "m_default"

    r = client.put(f"/lab/projects/{pid}/models/active", json={"model_id": new_id})
    assert r.status_code == 200, r.text
    blob = r.json()
    assert blob["model_id"] == new_id
    assert blob["label"] == "Sonnet 4.6"
    assert blob["provider"] == "anthropic"

    # Persisted: a fresh GET returns the same active model.
    after = client.get(f"/lab/projects/{pid}/models/active").json()
    assert after["model_id"] == new_id


def test_put_active_model_unknown_id_returns_404(workspace: Path) -> None:
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    r = client.put(
        f"/lab/projects/{pid}/models/active",
        json={"model_id": "m_nope_never_existed"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "model_not_found"

    # Active model is unchanged.
    blob = client.get(f"/lab/projects/{pid}/models/active").json()
    assert blob["model_id"] == "m_default"


def test_put_active_model_missing_body_field_422(workspace: Path) -> None:
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    r = client.put(f"/lab/projects/{pid}/models/active", json={})
    assert r.status_code == 422  # pydantic validation


def test_put_active_model_last_writer_wins(workspace: Path) -> None:
    """No OCC token — sequential writes both succeed; latest wins (mirrors
    prompts/active semantics).
    """
    pid = asyncio.run(_create(workspace, name="t"))["slug"]
    a_id = asyncio.run(_create_model(
        workspace, pid,
        label="A", provider="anthropic", provider_model_id="claude-sonnet-4-6",
    ))
    b_id = asyncio.run(_create_model(
        workspace, pid,
        label="B", provider="anthropic", provider_model_id="claude-opus-4-6",
    ))

    r1 = client.put(f"/lab/projects/{pid}/models/active", json={"model_id": a_id})
    assert r1.status_code == 200
    assert r1.json()["model_id"] == a_id

    r2 = client.put(f"/lab/projects/{pid}/models/active", json={"model_id": b_id})
    assert r2.status_code == 200
    assert r2.json()["model_id"] == b_id

    assert client.get(f"/lab/projects/{pid}/models/active").json()["model_id"] == b_id


def test_put_active_model_unknown_project_404(workspace: Path) -> None:
    r = client.put(
        "/lab/projects/p_does_not_exist/models/active",
        json={"model_id": "m_default"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error_code"] == "project_not_found"
