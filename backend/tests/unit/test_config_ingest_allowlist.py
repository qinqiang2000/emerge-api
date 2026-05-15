"""`Settings.ingest_allowlist()` must include the built-in roots and append
env-supplied extras."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings


def test_ingest_allowlist_includes_builtins() -> None:
    s = Settings()
    roots = s.ingest_allowlist()
    # /tmp is always allowed (one-off scratch).
    tmp_resolved = Path("/tmp").resolve()
    assert tmp_resolved in roots
    # Repo root should be present. From this test:
    # backend/tests/unit/test_*.py → backend/tests/unit → backend/tests → backend → emerge.
    repo_root = Path(__file__).resolve().parents[3]
    assert repo_root in roots


def test_ingest_allowlist_extends_with_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    custom = tmp_path / "shared-scans"
    custom.mkdir()
    monkeypatch.setenv("EMERGE_INGEST_LOCAL_EXTRA_ROOTS", str(custom))
    s = Settings()
    roots = s.ingest_allowlist()
    assert custom.resolve() in roots
    # built-in roots still there.
    assert Path("/tmp").resolve() in roots


def test_ingest_allowlist_dedupes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMERGE_INGEST_LOCAL_EXTRA_ROOTS", "/tmp:/tmp")
    s = Settings()
    roots = s.ingest_allowlist()
    tmp_resolved = Path("/tmp").resolve()
    assert roots.count(tmp_resolved) == 1
