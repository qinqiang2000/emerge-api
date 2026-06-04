"""Post slug-transparency the keys/meta endpoint is workspace-level
(`/lab/keys/meta`), not project-scoped. Keys belong to a `user_id` (default
placeholder `"default"`) and one key calls any `published_id`."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tools.publish import issue_api_key


@pytest.mark.asyncio
async def test_keys_meta_returns_hash_only(workspace) -> None:
    issued = await issue_api_key(user_id="default")
    client = TestClient(app)
    r = client.get("/lab/keys/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "default"
    assert body["key_hash_short"] == issued["key_hash"][-6:]
    assert body["created_at"]
    assert "key_plaintext" not in body


@pytest.mark.asyncio
async def test_keys_meta_empty_when_no_key(workspace) -> None:
    client = TestClient(app)
    r = client.get("/lab/keys/meta")
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == "default"
    assert body["key_hash_short"] is None
    assert body["created_at"] is None
