import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.projects import create_project
from app.tools.publish import issue_api_key


@pytest.mark.asyncio
async def test_keys_meta_returns_hash_only(workspace) -> None:
    pid = (await create_project(workspace, name="p"))["slug"]
    issued = await issue_api_key(workspace, pid)
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/keys/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert body["key_hash_short"] == issued["key_hash"][-6:]
    assert body["created_at"]
    assert "key_plaintext" not in body


@pytest.mark.asyncio
async def test_keys_meta_empty_when_no_key(workspace) -> None:
    pid = (await create_project(workspace, name="p"))["slug"]
    client = TestClient(app)
    r = client.get(f"/lab/projects/{pid}/keys/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert body["key_hash_short"] is None
    assert body["created_at"] is None
