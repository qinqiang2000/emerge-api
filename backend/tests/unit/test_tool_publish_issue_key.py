import json
import logging
from pathlib import Path

import pytest

from app.security.keys import KEY_PREFIX, get_keystore, sha256_key
from app.tools.publish import issue_api_key
from app.workspace.paths import keys_path


@pytest.mark.asyncio
async def test_issue_returns_envelope(tmp_path: Path) -> None:
    out = await issue_api_key(tmp_path)
    assert set(out.keys()) == {"key_plaintext", "key_hash", "key_prefix", "created_at"}
    assert out["key_plaintext"].startswith(KEY_PREFIX)
    assert sha256_key(out["key_plaintext"]) == out["key_hash"]
    assert out["key_prefix"] == out["key_plaintext"][:11]


@pytest.mark.asyncio
async def test_issue_writes_only_hash(tmp_path: Path) -> None:
    out = await issue_api_key(tmp_path)
    blob = json.loads(keys_path(tmp_path).read_text())
    assert len(blob) == 1
    row = blob[0]
    assert row["hash"] == out["key_hash"]
    assert row["user_id"] == "default"
    assert "project_id" not in row
    full = keys_path(tmp_path).read_text()
    assert out["key_plaintext"] not in full


@pytest.mark.asyncio
async def test_issue_rotates_existing(tmp_path: Path) -> None:
    first = await issue_api_key(tmp_path)
    second = await issue_api_key(tmp_path)
    assert first["key_plaintext"] != second["key_plaintext"]
    blob = json.loads(keys_path(tmp_path).read_text())
    assert len(blob) == 1
    assert blob[0]["hash"] == second["key_hash"]
    store = get_keystore(tmp_path)
    assert store.lookup(first["key_plaintext"]) is None
    assert store.lookup(second["key_plaintext"]) is not None


@pytest.mark.asyncio
async def test_issue_never_logs_plaintext(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="app.tools.publish")
    caplog.set_level(logging.DEBUG, logger="app.security.keys")
    out = await issue_api_key(tmp_path)
    for rec in caplog.records:
        assert out["key_plaintext"] not in rec.getMessage()
