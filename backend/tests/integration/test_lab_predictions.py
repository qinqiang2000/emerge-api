from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import predictions_draft_dir


async def test_get_prediction_200(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    pdir = predictions_draft_dir(workspace, pid)
    pdir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(pdir / "d_aaaaaaaaaaaa.json", {"entities": [{"x": 1}]})
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/d_aaaaaaaaaaaa")
    assert r.status_code == 200
    assert r.json() == {"entities": [{"x": 1}]}


async def test_get_prediction_404_when_missing(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/predictions/d_nopenopenope")
    assert r.status_code == 404


def test_get_prediction_400_on_bad_pid() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_INVALIDPATH/predictions/d_aaaaaaaaaaaa")
    assert r.status_code == 400
