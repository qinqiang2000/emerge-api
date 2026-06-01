"""Route test for the experiment-prediction grounding render-support endpoint.

POST /lab/projects/{slug}/experiments/{eid}/predictions/{filename:path}/ground

``ground_entities`` + the model/experiment/path lookups are monkeypatched at the
route module, so this exercises only the route's safety + guard + write-back +
envelope plumbing — not a real provider call. Mirrors test_ground_route.py.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.routes.experiments as exp_route
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class _Blob:
    """Fake experiment prediction path: exists + read_text return a JSON blob."""

    def __init__(self, data: dict):
        self._data = data

    def exists(self) -> bool:
        return True


class _MissingBlob:
    def exists(self) -> bool:
        return False


def _wire(monkeypatch, *, blob: dict, missing: bool = False):
    """Patch the route's collaborators so only the route logic runs.

    Returns a ``captured`` dict that records the entities passed to
    ``ground_entities`` and the blob handed to ``atomic_write_json``.
    """
    captured: dict = {}

    monkeypatch.setattr(exp_route, "_project_or_404", lambda slug: Path("/ws"))

    async def fake_migrate(ws, slug):
        return None

    monkeypatch.setattr(exp_route, "migrate_project_if_needed", fake_migrate)

    async def fake_read_experiment(ws, slug, eid):
        return SimpleNamespace(model_id="m_exp")

    monkeypatch.setattr(exp_route, "read_experiment", fake_read_experiment)

    path_obj = _MissingBlob() if missing else _Blob(blob)
    # read_text is invoked on the path; return the live blob JSON each call.
    if not missing:
        path_obj.read_text = lambda encoding="utf-8": json.dumps(blob)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        exp_route, "experiment_prediction_path", lambda ws, s, e, f: path_obj
    )

    async def fake_read_model(ws, slug, mid):
        captured["model_id_arg"] = mid
        return SimpleNamespace(provider_model_id="gemini-x", provider="gemini")

    monkeypatch.setattr(exp_route, "read_model", fake_read_model)
    monkeypatch.setattr(
        exp_route, "get_provider_for_model", lambda pmid, provider=None: object()
    )

    @contextlib.asynccontextmanager
    async def fake_lock(ws, slug):
        yield

    monkeypatch.setattr(exp_route, "project_lock", fake_lock)

    def fake_write(path, obj):
        captured["written"] = obj

    monkeypatch.setattr(exp_route, "atomic_write_json", fake_write)
    return captured, path_obj


def test_ground_experiment_happy_path_writes_back(client, monkeypatch):
    blob = {"entities": [{"currency": "USD"}], "_evidence": None}
    captured, _ = _wire(monkeypatch, blob=blob)

    async def fake_ground(ws, pid, fname, entities, *, provider, model_id):
        captured["entities"] = entities
        captured["model_id"] = model_id
        return [{"currency": {"page": 1, "source": "USD"}}]

    monkeypatch.setattr(exp_route, "ground_entities", fake_ground)

    resp = client.post(
        "/lab/projects/acme/experiments/ex_1/predictions/inv.pdf/ground", json={}
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"][0]["currency"]["source"] == "USD"
    # grounded the blob's existing entities (no re-extract) with the experiment model
    assert captured["entities"] == [{"currency": "USD"}]
    assert captured["model_id"] == "gemini-x"
    assert captured["model_id_arg"] == "m_exp"
    # evidence stamped back into the blob
    assert captured["written"]["_evidence"][0]["currency"]["source"] == "USD"


def test_ground_experiment_skips_when_already_grounded(client, monkeypatch):
    blob = {
        "entities": [{"currency": "USD"}],
        "_evidence": [{"currency": {"page": 2, "source": "USD"}}],
    }
    captured, _ = _wire(monkeypatch, blob=blob)

    async def fake_ground(*a, **k):
        raise AssertionError("ground_entities must not run when already grounded")

    monkeypatch.setattr(exp_route, "ground_entities", fake_ground)

    resp = client.post(
        "/lab/projects/acme/experiments/ex_1/predictions/inv.pdf/ground", json={}
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"][0]["currency"]["page"] == 2
    assert "written" not in captured  # cache short-circuit, no re-write


def test_ground_experiment_force_reground(client, monkeypatch):
    blob = {
        "entities": [{"currency": "USD"}],
        "_evidence": [{"currency": {"page": 2, "source": "stale"}}],
    }
    captured, _ = _wire(monkeypatch, blob=blob)

    async def fake_ground(ws, pid, fname, entities, *, provider, model_id):
        return [{"currency": {"page": 9, "source": "fresh"}}]

    monkeypatch.setattr(exp_route, "ground_entities", fake_ground)

    resp = client.post(
        "/lab/projects/acme/experiments/ex_1/predictions/inv.pdf/ground",
        json={"force": True},
    )
    assert resp.status_code == 200
    assert resp.json()["evidence"][0]["currency"]["page"] == 9
    assert captured["written"]["_evidence"][0]["currency"]["source"] == "fresh"


def test_ground_experiment_transient_provider_error_envelope(client, monkeypatch):
    """A flaky-proxy ConnectError must return a structured 503 + `transient`,
    not a raw 500 — mirror of the /ground route envelope."""
    import httpx

    blob = {"entities": [{"currency": "USD"}], "_evidence": None}
    _wire(monkeypatch, blob=blob)

    async def fake_ground(*a, **k):
        raise httpx.ConnectError("")  # empty message — the 振兴 proxy blip

    monkeypatch.setattr(exp_route, "ground_entities", fake_ground)

    resp = client.post(
        "/lab/projects/acme/experiments/ex_1/predictions/inv.pdf/ground", json={}
    )
    assert resp.status_code == 503
    body = resp.json()["detail"]
    assert body["error_code"] == "ground_provider_unavailable"
    assert body["transient"] is True
    assert body["error_message_en"] == "ConnectError"  # blank str(exc) not collapsed


def test_ground_experiment_experiment_not_found(client, monkeypatch):
    _wire(monkeypatch, blob={}, missing=True)

    async def fake_read_experiment(ws, slug, eid):
        raise exp_route.ExperimentNotFoundError("nope")

    monkeypatch.setattr(exp_route, "read_experiment", fake_read_experiment)

    resp = client.post(
        "/lab/projects/acme/experiments/ex_x/predictions/inv.pdf/ground", json={}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "experiment_not_found"


def test_ground_experiment_prediction_not_found(client, monkeypatch):
    _wire(monkeypatch, blob={}, missing=True)
    resp = client.post(
        "/lab/projects/acme/experiments/ex_1/predictions/missing.pdf/ground", json={}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "experiment_prediction_not_found"
