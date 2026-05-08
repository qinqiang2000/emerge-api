from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project


async def test_list_projects_returns_created(workspace: Path) -> None:
    pid = await create_project(workspace, name="inv-MY")
    client = TestClient(app)
    r = client.get("/lab/projects")
    assert r.status_code == 200
    items = r.json()
    assert any(it["project_id"] == pid for it in items)


async def test_get_one_project(workspace: Path) -> None:
    pid = await create_project(workspace, name="x")
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "x"


def test_get_unknown_project_404() -> None:
    client = TestClient(app)
    r = client.get("/lab/projects/p_doesnotexist")
    assert r.status_code == 404
