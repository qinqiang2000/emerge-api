"""Schema coverage for `_keys.json` rows post-slug-transparency.

Keys are now user-scoped, not project-scoped — one live key per
`(user_id, scope)` pair, callable against any frozen `published_id`. The
row schema is `{hash, user_id, scope, created_at, last_used}` with NO
`project_id` field; we only test the contract here so future migrations
can lean on these assertions."""
from __future__ import annotations

import json
from pathlib import Path

from app.security.keys import KeyStore, generate_key, sha256_key
from app.workspace.paths import keys_path


def test_upsert_for_user_replaces_same_user_scope(tmp_path: Path) -> None:
    """Two upserts for the same `(user_id, scope)` keep exactly one row."""
    store = KeyStore(keys_path(tmp_path))
    store.load()
    old = generate_key()
    new = generate_key()
    store.upsert_for_user("default", old, scope="extract")
    store.upsert_for_user("default", new, scope="extract")

    blob = json.loads(keys_path(tmp_path).read_text())
    same_pair = [r for r in blob if r["user_id"] == "default" and r["scope"] == "extract"]
    assert len(same_pair) == 1
    assert same_pair[0]["hash"] == sha256_key(new)
    assert store.lookup(old) is None
    assert store.lookup(new) is not None


def test_upsert_for_user_keeps_other_user_rows(tmp_path: Path) -> None:
    """Rotating user-A's key must NOT drop user-B's row."""
    store = KeyStore(keys_path(tmp_path))
    store.load()
    a_old = generate_key()
    a_new = generate_key()
    b_key = generate_key()
    store.upsert_for_user("alice", a_old, scope="extract")
    store.upsert_for_user("bob", b_key, scope="extract")
    store.upsert_for_user("alice", a_new, scope="extract")

    assert store.lookup(a_old) is None
    assert store.lookup(a_new) is not None
    assert store.lookup(b_key) is not None


def test_lookup_returns_user_id_not_project_id(tmp_path: Path) -> None:
    store = KeyStore(keys_path(tmp_path))
    store.load()
    plaintext = generate_key()
    store.upsert_for_user("default", plaintext)
    row = store.lookup(plaintext)
    assert row is not None
    assert row["user_id"] == "default"
    # Pre-rewrite, lookup returned `project_id`; the new contract has no such
    # field. Future migrations grep for this name — keep the assertion sharp.
    assert "project_id" not in row


def test_keys_json_schema_user_id_field(tmp_path: Path) -> None:
    """Each persisted row carries exactly the canonical user-scoped fields."""
    store = KeyStore(keys_path(tmp_path))
    store.load()
    store.upsert_for_user("default", generate_key())

    blob = json.loads(keys_path(tmp_path).read_text())
    assert len(blob) == 1
    row = blob[0]
    assert set(row.keys()) == {"hash", "user_id", "scope", "created_at", "last_used"}
    # ISO timestamp ends in Z (UTC) — keeps logs grep-friendly.
    assert isinstance(row["created_at"], str) and row["created_at"].endswith("Z")
    assert row["last_used"] is None
