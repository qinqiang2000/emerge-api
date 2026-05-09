from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_json

KEY_PREFIX = "ek_"
_KEY_BYTES = 24


def generate_key() -> str:
    """Return a fresh 192-bit API key as `ek_` + 32 url-safe chars."""
    return KEY_PREFIX + secrets.token_urlsafe(_KEY_BYTES)


def sha256_key(plaintext: str) -> str:
    """Return lowercase-hex sha256 for key storage and lookup."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def key_prefix_display(plaintext: str) -> str:
    """Return the safe display prefix: `ek_` + 8 chars."""
    return plaintext[:11]


def key_hash_short(hash_hex: str) -> str:
    """Return the last 6 hex chars of a sha256 digest."""
    return hash_hex[-6:]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class KeyStore:
    """In-memory cache of `_keys.json` for O(1) prod-path lookups."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._by_hash: dict[str, dict[str, Any]] = {}
        self._mtime: float | None = None

    def load(self) -> None:
        self._reload_from_disk()

    def _reload_from_disk(self) -> None:
        if not self._path.exists():
            self._by_hash = {}
            self._mtime = None
            return
        try:
            blob = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            blob = []
        self._by_hash = {
            row["hash"]: row
            for row in blob
            if isinstance(row, dict) and isinstance(row.get("hash"), str)
        }
        self._mtime = self._path.stat().st_mtime

    def reload_if_changed(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            if self._by_hash:
                self._by_hash = {}
                self._mtime = None
            return
        if self._mtime is None or mtime != self._mtime:
            self._reload_from_disk()

    def lookup(self, plaintext: str) -> dict[str, Any] | None:
        self.reload_if_changed()
        row = self._by_hash.get(sha256_key(plaintext))
        return dict(row) if row is not None else None

    def upsert_for_project(self, project_id: str, plaintext: str, *, scope: str = "extract") -> None:
        self.reload_if_changed()
        rows = [r for r in self._by_hash.values() if r.get("project_id") != project_id]
        rows.append({
            "hash": sha256_key(plaintext),
            "project_id": project_id,
            "scope": scope,
            "created_at": _iso_now(),
            "last_used": None,
        })
        atomic_write_json(self._path, rows)
        self._by_hash = {r["hash"]: r for r in rows}
        self._mtime = self._path.stat().st_mtime

    def update_last_used(self, hash_hex: str, ts: str) -> None:
        self.reload_if_changed()
        rows = list(self._by_hash.values())
        for row in rows:
            if row["hash"] == hash_hex:
                row["last_used"] = ts
                break
        else:
            return
        atomic_write_json(self._path, rows)
        self._by_hash = {r["hash"]: r for r in rows}
        self._mtime = self._path.stat().st_mtime


_STORES: dict[Path, KeyStore] = {}


def get_keystore(workspace: Path) -> KeyStore:
    from app.workspace.paths import keys_path

    path = keys_path(workspace)
    if path not in _STORES:
        store = KeyStore(path)
        store.load()
        _STORES[path] = store
    return _STORES[path]
