from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_post_reviewed_writes_file(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    body = {
        "entities": [{"invoice_no": "INV-1", "total_amount": 99.5}],
        "source": "manual",
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/d_aaaaaaaaaaaa", json=body)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    saved = (workspace / pid / "reviewed" / "d_aaaaaaaaaaaa.json").read_text()
    assert "INV-1" in saved
    assert '"source": "manual"' in saved


async def test_post_reviewed_with_notes(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    body = {
        "entities": [{"buyer_name": "ACME"}],
        "source": "manual",
        "notes": {"buyer_name": "official: ACME Sdn Bhd"},
    }
    r = client.post(f"/lab/projects/{pid}/reviewed/d_aaaaaaaaaaaa", json=body)
    assert r.status_code == 200
    saved = (workspace / pid / "reviewed" / "d_aaaaaaaaaaaa.json").read_text()
    assert "official: ACME Sdn Bhd" in saved


async def test_get_reviewed_returns_payload(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    client.post(
        f"/lab/projects/{pid}/reviewed/d_aaaaaaaaaaaa",
        json={"entities": [{"x": 1}], "source": "manual"},
    )
    r = client.get(f"/lab/projects/{pid}/reviewed/d_aaaaaaaaaaaa")
    assert r.status_code == 200
    assert r.json()["entities"] == [{"x": 1}]


def test_get_reviewed_404_when_missing() -> None:
    client = TestClient(app)
    # valid-format pid + did that don't exist on disk
    r = client.get("/lab/projects/p_abcdef012345/reviewed/d_abcdef012345")
    assert r.status_code == 404


def test_post_reviewed_400_on_bad_pid() -> None:
    client = TestClient(app)
    # uppercase pid fails ^p_[a-z0-9]{12}$
    r = client.post(
        "/lab/projects/p_INVALIDPATH/reviewed/d_abcdef012345",
        json={"entities": [], "source": "manual"},
    )
    assert r.status_code == 400


def test_post_reviewed_422_on_bad_body() -> None:
    client = TestClient(app)
    r = client.post(
        "/lab/projects/p_abcdef012345/reviewed/d_abcdef012345",
        json={"entities": "not-a-list", "source": "manual"},
    )
    assert r.status_code == 422
