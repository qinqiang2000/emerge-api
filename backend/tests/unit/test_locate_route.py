"""Route test for the field-source-grounding locate render endpoint.

The resolver (`locate_fields`) and the doc-existence check (`doc_path`) are
monkeypatched at the route module so the test is independent of the on-disk
workspace layout — it exercises only the route's safety + envelope + body
plumbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.locate as locate_route
from app.main import app
from app.schemas.locate import FieldLocation


@pytest.fixture
def client():
    return TestClient(app)


class _ExistingPath:
    def exists(self):
        return True


class _MissingPath:
    def exists(self):
        return False


def test_locate_returns_field_locations(client, monkeypatch):
    monkeypatch.setattr(locate_route, "doc_path", lambda ws, s, f: _ExistingPath())

    async def fake_locate(ws, pid, fname, *, entities, evidence, target_lang=None):
        return [
            FieldLocation(
                entity_index=0,
                path="vendor",
                rects=[[10.0, 20.0, 110.0, 32.0]],
                page=1,
                status="exact",
                score=100.0,
            )
        ]

    monkeypatch.setattr(locate_route, "locate_fields", fake_locate)
    resp = client.post(
        "/lab/projects/acme/docs/by-name/inv.pdf/locate",
        json={"entities": [{"vendor": "Acme"}], "evidence": [{"vendor": {"page": 1}}]},
    )
    assert resp.status_code == 200
    bodyj = resp.json()
    assert bodyj[0]["status"] == "exact"
    assert bodyj[0]["rects"] == [[10.0, 20.0, 110.0, 32.0]]
    assert bodyj[0]["path"] == "vendor"


def test_locate_evidence_null_ok(client, monkeypatch):
    monkeypatch.setattr(locate_route, "doc_path", lambda ws, s, f: _ExistingPath())
    captured = {}

    async def fake_locate(ws, pid, fname, *, entities, evidence, target_lang=None):
        captured["evidence"] = evidence
        return []

    monkeypatch.setattr(locate_route, "locate_fields", fake_locate)
    resp = client.post(
        "/lab/projects/acme/docs/by-name/inv.pdf/locate",
        json={"entities": [{"vendor": "Acme"}], "evidence": None},
    )
    assert resp.status_code == 200
    assert resp.json() == []
    assert captured["evidence"] is None


def test_locate_doc_not_found(client, monkeypatch):
    monkeypatch.setattr(locate_route, "doc_path", lambda ws, s, f: _MissingPath())
    resp = client.post(
        "/lab/projects/acme/docs/by-name/missing.pdf/locate",
        json={"entities": [], "evidence": None},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "doc_not_found"
