import json
import logging
from pathlib import Path

import pytest

from app.config import get_settings
from app.security.keys import KEY_PREFIX, get_keystore, sha256_key
from app.tools.publish import issue_api_key
from app.workspace.paths import keys_path

# The keystore is a GLOBAL prod resource: `issue_api_key` takes no workspace and
# always writes `_keys.json` at the TRUE root (`settings.workspace_root`, which
# `env_isolation` points at the per-test `workspace` fixture). Prod `/v1/extract`
# reads it there; a per-team path would never validate (2026-06-04 finding).


@pytest.mark.asyncio
async def test_issue_returns_envelope() -> None:
    out = await issue_api_key()
    assert set(out.keys()) == {"key_plaintext", "key_hash", "key_prefix", "created_at"}
    assert out["key_plaintext"].startswith(KEY_PREFIX)
    assert sha256_key(out["key_plaintext"]) == out["key_hash"]
    assert out["key_prefix"] == out["key_plaintext"][:11]


@pytest.mark.asyncio
async def test_issue_writes_only_hash_at_true_root(workspace: Path) -> None:
    out = await issue_api_key()
    root = get_settings().workspace_root
    assert root == workspace  # env_isolation pins settings root at the fixture
    blob = json.loads(keys_path(root).read_text())
    assert len(blob) == 1
    row = blob[0]
    assert row["hash"] == out["key_hash"]
    assert row["user_id"] == "default"
    assert "project_id" not in row
    assert out["key_plaintext"] not in keys_path(root).read_text()


@pytest.mark.asyncio
async def test_issue_rotates_existing(workspace: Path) -> None:
    first = await issue_api_key()
    second = await issue_api_key()
    assert first["key_plaintext"] != second["key_plaintext"]
    root = get_settings().workspace_root
    blob = json.loads(keys_path(root).read_text())
    assert len(blob) == 1
    assert blob[0]["hash"] == second["key_hash"]
    store = get_keystore(root)
    assert store.lookup(first["key_plaintext"]) is None
    assert store.lookup(second["key_plaintext"]) is not None


@pytest.mark.asyncio
async def test_issue_never_logs_plaintext(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="app.tools.publish")
    caplog.set_level(logging.DEBUG, logger="app.security.keys")
    out = await issue_api_key()
    for rec in caplog.records:
        assert out["key_plaintext"] not in rec.getMessage()
