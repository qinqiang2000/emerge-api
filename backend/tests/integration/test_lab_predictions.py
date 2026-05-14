from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_get_prediction_200(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / "inv-001.pdf.json", {"entities": [{"x": 1}]})
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/inv-001.pdf")
    assert r.status_code == 200
    assert r.json() == {"entities": [{"x": 1}]}


async def test_get_prediction_404_when_missing(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/nope.pdf")
    assert r.status_code == 404


def test_get_prediction_404_on_unknown_slug() -> None:
    """Slug shapes pass safe_slug; existence check returns 404."""
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/predictions/anything.pdf")
    assert r.status_code == 404
