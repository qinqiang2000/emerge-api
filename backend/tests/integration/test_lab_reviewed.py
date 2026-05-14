from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_post_reviewed_writes_file(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    body = {
        "entities": [{"invoice_no": "INV-1", "total_amount": 99.5}],
        "source": "manual",
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/inv-001.pdf", json=body)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    saved = (workspace / pid / "reviewed" / "inv-001.pdf.json").read_text()
    assert "INV-1" in saved
    assert '"source": "manual"' in saved


async def test_post_reviewed_with_notes(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    body = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "notes": {"buyer_name": "official: ACME Sdn Bhd"},
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/inv-001.pdf", json=body)
    assert r.status_code == 200
    saved = (workspace / pid / "reviewed" / "inv-001.pdf.json").read_text()
    assert "official: ACME Sdn Bhd" in saved


async def test_post_reviewed_with_evidence(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    body = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "_evidence": [{"buyer_name": 2}],
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/inv-001.pdf", json=body)
    assert r.status_code == 200
    saved = (workspace / pid / "reviewed" / "inv-001.pdf.json").read_text()
    assert '"_evidence"' in saved
    assert '"buyer_name": 2' in saved


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    client.post(
        f"/lab/projects/{pid}/reviewed/inv-001.pdf",
        json={"entities": [{"x": 1}], "source": "manual"},
    )
    r = client.get(f"/lab/projects/{pid}/reviewed/inv-001.pdf")
    assert r.status_code == 200
    assert r.json()["entities"] == [{"x": 1}]


def test_get_reviewed_404_when_missing() -> None:
    client = TestClient(app)
    # valid-format pid + nonexistent filename
    r = client.get("/lab/projects/p_abcdef012345/reviewed/missing.pdf")
    assert r.status_code == 404


def test_post_reviewed_400_on_bad_pid() -> None:
    client = TestClient(app)
    # uppercase pid fails ^p_[a-z0-9]{12}$
    r = client.post(
        "/lab/projects/p_INVALIDPATH/reviewed/any.pdf",
        json={"entities": [], "source": "manual"},
    )
    assert r.status_code == 400


def test_post_reviewed_422_on_bad_body() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/p_abcdef012345/reviewed/any.pdf",
        json={"entities": "not-a-list", "source": "manual"},
    )
    assert r.status_code == 422


async def test_post_get_reviewed_multi_entity(workspace: Path) -> None:
    """POST + GET reviewed preserves a multi-entity payload exactly."""
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    body = {
        "entities": [
            {"invoice_number": "A1"},
            {"invoice_number": "B2"},
        ],
        "source": "manual",
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/inv-001.pdf", json=body)
    assert r.status_code == 200
    g = client.get(f"/lab/projects/{pid}/reviewed/inv-001.pdf")
    assert g.status_code == 200
    assert g.json()["entities"] == body["entities"]
