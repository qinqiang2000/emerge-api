"""Route test for the grounding render-support endpoint.

``ground_prediction`` + the doc-existence check are monkeypatched at the route
module, so this exercises only the route's safety + envelope + body plumbing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.api.routes.ground as ground_route
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class _ExistingPath:
    def exists(self):
        return True


class _MissingPath:
    def exists(self):
        return False


def test_ground_returns_evidence(client, monkeypatch):
    monkeypatch.setattr(ground_route, "doc_path", lambda ws, s, f: _ExistingPath())
    captured = {}

    async def fake_ground(ws, pid, fname, *, tab, entities, force):
        captured["tab"] = tab
        captured["force"] = force
        return [{"currency": {"page": 1, "source": "USD"}}]

    monkeypatch.setattr(ground_route, "ground_prediction", fake_ground)
    resp = client.post(
        "/lab/projects/acme/docs/by-name/inv.pdf/ground",
        json={"tab": "_pending", "force": True},
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"][0]["currency"]["source"] == "USD"
    assert captured == {"tab": "_pending", "force": True}


def test_ground_defaults_to_draft_on_empty_body(client, monkeypatch):
    monkeypatch.setattr(ground_route, "doc_path", lambda ws, s, f: _ExistingPath())
    captured = {}

    async def fake_ground(ws, pid, fname, *, tab, entities, force):
        captured["tab"] = tab
        return []

    monkeypatch.setattr(ground_route, "ground_prediction", fake_ground)
    resp = client.post("/lab/projects/acme/docs/by-name/inv.pdf/ground")
    assert resp.status_code == 200
    assert captured["tab"] == "_draft"


def test_ground_doc_not_found(client, monkeypatch):
    monkeypatch.setattr(ground_route, "doc_path", lambda ws, s, f: _MissingPath())
    resp = client.post(
        "/lab/projects/acme/docs/by-name/missing.pdf/ground", json={}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "doc_not_found"


def test_ground_prediction_not_found(client, monkeypatch):
    monkeypatch.setattr(ground_route, "doc_path", lambda ws, s, f: _ExistingPath())

    async def fake_ground(ws, pid, fname, *, tab, entities, force):
        raise FileNotFoundError("no _draft prediction")

    monkeypatch.setattr(ground_route, "ground_prediction", fake_ground)
    resp = client.post("/lab/projects/acme/docs/by-name/inv.pdf/ground", json={})
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "prediction_not_found"
