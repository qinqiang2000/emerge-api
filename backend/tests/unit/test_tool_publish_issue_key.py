import json
import logging
from pathlib import Path

import pytest

from app.security.keys import KEY_PREFIX, get_keystore, sha256_key
from app.tools.publish import issue_api_key
from app.workspace.atomic import atomic_write_json
from app.workspace.paths import (
    keys_path,
    project_dir,
    project_json_path,
    schema_path,
)


def _bare_project(workspace: Path, pid: str) -> None:
    project_dir(workspace, pid).mkdir(parents=True, exist_ok=True)
    atomic_write_json(project_json_path(workspace, pid), {
        "name": "p", "project_type": "extraction", "created_at": "x",
        "extract_model": "claude-sonnet-4-6", "extract_params": {},
        "active_version_id": "v1",
    })
    atomic_write_json(schema_path(workspace, pid), [])


@pytest.mark.asyncio
async def test_issue_returns_envelope(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bare_project(tmp_path, pid)
    out = await issue_api_key(tmp_path, pid)
    assert set(out.keys()) == {"key_plaintext", "key_hash", "key_prefix", "created_at"}
    assert out["key_plaintext"].startswith(KEY_PREFIX)
    assert sha256_key(out["key_plaintext"]) == out["key_hash"]
    assert out["key_prefix"] == out["key_plaintext"][:11]


@pytest.mark.asyncio
async def test_issue_writes_only_hash(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bare_project(tmp_path, pid)
    out = await issue_api_key(tmp_path, pid)
    blob = json.loads(keys_path(tmp_path).read_text())
    assert len(blob) == 1
    row = blob[0]
    assert row["hash"] == out["key_hash"]
    assert row["project_id"] == pid
    full = keys_path(tmp_path).read_text()
    assert out["key_plaintext"] not in full


@pytest.mark.asyncio
async def test_issue_rotates_existing(tmp_path: Path) -> None:
    pid = "p_abc123def456"
    _bare_project(tmp_path, pid)
    first = await issue_api_key(tmp_path, pid)
    second = await issue_api_key(tmp_path, pid)
    assert first["key_plaintext"] != second["key_plaintext"]
    blob = json.loads(keys_path(tmp_path).read_text())
    assert len(blob) == 1
    assert blob[0]["hash"] == second["key_hash"]
    store = get_keystore(tmp_path)
    assert store.lookup(first["key_plaintext"]) is None
    assert store.lookup(second["key_plaintext"]) is not None


@pytest.mark.asyncio
async def test_issue_never_logs_plaintext(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    pid = "p_abc123def456"
    _bare_project(tmp_path, pid)
    caplog.set_level(logging.DEBUG, logger="app.tools.publish")
    caplog.set_level(logging.DEBUG, logger="app.security.keys")
    out = await issue_api_key(tmp_path, pid)
    for rec in caplog.records:
        assert out["key_plaintext"] not in rec.getMessage()
