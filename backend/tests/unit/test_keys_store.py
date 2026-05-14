import json
import time
from pathlib import Path

from app.security.keys import KeyStore, generate_key, sha256_key
from app.workspace.paths import keys_path


def test_load_empty_or_missing_file_returns_empty(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    assert store.lookup("ek_anything") is None


def test_upsert_then_lookup(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    plaintext = generate_key()
    store.upsert_for_user("default", plaintext)
    row = store.lookup(plaintext)
    assert row is not None
    assert row["user_id"] == "default"
    assert "project_id" not in row
    assert row["scope"] == "extract"
    assert row["last_used"] is None
    blob = json.loads(keys_path(tmp_path).read_text())
    assert all("plaintext" not in r and "key_plaintext" not in r for r in blob)
    assert blob[0]["hash"] == sha256_key(plaintext)


def test_upsert_overwrites_existing_for_same_user_scope(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    old = generate_key()
    new = generate_key()
    store.upsert_for_user("default", old)
    store.upsert_for_user("default", new)
    assert store.lookup(old) is None
    assert store.lookup(new) is not None
    blob = json.loads(keys_path(tmp_path).read_text())
    rows_for_user = [r for r in blob if r["user_id"] == "default" and r["scope"] == "extract"]
    assert len(rows_for_user) == 1


def test_lookup_unknown_returns_none(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    store.upsert_for_user("default", generate_key())
    assert store.lookup("ek_unknownkey") is None


def test_reload_picks_up_external_change(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    new_key = generate_key()
    blob = [{
        "hash": sha256_key(new_key),
        "user_id": "default",
        "scope": "extract",
        "created_at": "2026-05-09T00:00:00Z",
        "last_used": None,
    }]
    keys_path(tmp_path).write_text(json.dumps(blob))
    import os as _os
    future = time.time() + 2
    _os.utime(keys_path(tmp_path), (future, future))
    assert store.lookup(new_key) is not None


def test_update_last_used_persists(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    plaintext = generate_key()
    store.upsert_for_user("default", plaintext)
    h = sha256_key(plaintext)
    store.update_last_used(h, "2026-05-09T01:23:45Z")
    blob = json.loads(keys_path(tmp_path).read_text())
    assert blob[0]["last_used"] == "2026-05-09T01:23:45Z"


def test_get_keystore_returns_singleton_per_workspace(tmp_path: Path) -> None:
    from app.security.keys import get_keystore
    s1 = get_keystore(tmp_path)
    s2 = get_keystore(tmp_path)
    assert s1 is s2
