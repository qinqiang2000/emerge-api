"""Recycle-bin routes. Pins the promise every delete path makes ("recoverable
for 14 days") end to end: delete through the normal API, find it in the bin,
put it back, and get the artifacts — not just the file — returned."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import doc_path, reviewed_path


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("EMERGE_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("EMERGE_TEST_MODE", "1")
    return TestClient(app)


def test_trash_is_empty_before_anything_is_deleted(client: TestClient) -> None:
    assert client.get("/lab/trash").json() == []


def test_deleted_doc_round_trips_through_the_bin(client: TestClient, tmp_path: Path) -> None:
    slug = asyncio.run(create_project(tmp_path, name="t"))["slug"]
    asyncio.run(upload_doc(tmp_path, slug, SAMPLE_PDF, "invoice.pdf"))
    # Hand-corrected ground truth — the artifact that makes this worth having.
    atomic_write_json(reviewed_path(tmp_path, slug, "invoice.pdf"), {"entities": [{"v": 1}]})

    assert client.delete(f"/lab/projects/{slug}/docs/by-name/invoice.pdf").status_code == 200
    assert not doc_path(tmp_path, slug, "invoice.pdf").exists()

    rows = client.get("/lab/trash").json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["kind"], row["name"], row["project"]) == ("doc", "invoice.pdf", slug)
    assert row["restorable"] is True
    assert row["member_count"] >= 2  # doc + meta + reviewed

    r = client.post(f"/lab/trash/{row['entry']}/restore")
    assert r.status_code == 200
    assert r.json()["kind"] == "doc"

    assert doc_path(tmp_path, slug, "invoice.pdf").read_bytes() == SAMPLE_PDF
    import json
    assert json.loads(reviewed_path(tmp_path, slug, "invoice.pdf").read_text()) == {
        "entities": [{"v": 1}]
    }
    assert client.get("/lab/trash").json() == []  # entry consumed
    # And the doc is visible to the app again, not just present on disk.
    listed = client.get(f"/lab/projects/{slug}/docs").json()
    assert [d["filename"] for d in listed] == ["invoice.pdf"]


def test_deleted_project_round_trips(client: TestClient, tmp_path: Path) -> None:
    slug = asyncio.run(create_project(tmp_path, name="precious"))["slug"]
    assert client.delete(f"/lab/projects/{slug}").status_code == 200
    assert client.get(f"/lab/projects/{slug}").status_code == 404

    row = client.get("/lab/trash").json()[0]
    assert (row["kind"], row["name"]) == ("project", slug)
    assert client.post(f"/lab/trash/{row['entry']}/restore").status_code == 200
    assert client.get(f"/lab/projects/{slug}").status_code == 200


def test_restore_conflict_is_409_and_moves_nothing(client: TestClient, tmp_path: Path) -> None:
    slug = asyncio.run(create_project(tmp_path, name="t"))["slug"]
    asyncio.run(upload_doc(tmp_path, slug, SAMPLE_PDF, "a.pdf"))
    client.delete(f"/lab/projects/{slug}/docs/by-name/a.pdf")

    # The name gets taken back by a different upload.
    asyncio.run(upload_doc(tmp_path, slug, b"%PDF-1.4\ndifferent\n%%EOF\n", "a.pdf"))

    row = client.get("/lab/trash").json()[0]
    assert row["restorable"] is False
    assert row["blocked_reason"].startswith("origin_occupied:")

    r = client.post(f"/lab/trash/{row['entry']}/restore")
    assert r.status_code == 409
    assert r.json()["detail"]["error_code"] == "restore_blocked"
    # The live file is the new one, untouched, and the entry is still there.
    assert doc_path(tmp_path, slug, "a.pdf").read_bytes() != SAMPLE_PDF
    assert len(client.get("/lab/trash").json()) == 1


def test_restore_unknown_entry_404s(client: TestClient) -> None:
    assert client.post("/lab/trash/nope/restore").status_code == 404
    # Traversal attempts read as "not found", never as a path escape.
    assert client.post("/lab/trash/..%2F..%2Fetc/restore").status_code == 404


def test_bin_lists_newest_first(client: TestClient, tmp_path: Path) -> None:
    slug = asyncio.run(create_project(tmp_path, name="t"))["slug"]
    asyncio.run(upload_doc(tmp_path, slug, SAMPLE_PDF, "one.pdf"))
    asyncio.run(upload_doc(tmp_path, slug, SAMPLE_PDF, "two.pdf"))
    client.delete(f"/lab/projects/{slug}/docs/by-name/one.pdf")
    client.delete(f"/lab/projects/{slug}/docs/by-name/two.pdf")

    rows = client.get("/lab/trash").json()
    assert len(rows) == 2
    assert rows[0]["deleted_at"] >= rows[1]["deleted_at"]
