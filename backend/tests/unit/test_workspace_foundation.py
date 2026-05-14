"""Foundation tests for slug-transparency rollout (agent-1 scope).

Covers:
- `safe_slug` / `safe_published_id` validators (allow Unicode, reject path
  separators + control chars + reserved names).
- `new_published_id` shape (`pub_` + 12 base36 chars, unique per call).
- `published_path` layout under `_published/`.
- `PidIndex` register/resolve/unregister/rename happy paths.
- `paths.project_dir` keys by slug (folder name == slug).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.routes._safety import safe_published_id, safe_slug
from app.workspace.ids import new_published_id
from app.workspace.paths import project_dir, published_path
from app.workspace.pid_index import PidIndex


# ---------------------------------------------------------------------------
# safe_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "foo-bar",
        "美国发票",
        "q4-美国发票",
        "a",  # length 1 is allowed
        "x" * 64,  # length 64 is the upper bound (inclusive)
    ],
)
def test_safe_slug_accepts(value: str) -> None:
    assert safe_slug(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "foo/bar",
        "foo\\bar",
        ".",
        "..",
        "\x00bad",
        "bad\x1fname",
        "x" * 65,  # length 65 exceeds the 64-char cap
    ],
)
def test_safe_slug_rejects(value: str) -> None:
    with pytest.raises(HTTPException) as ei:
        safe_slug(value)
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# safe_published_id
# ---------------------------------------------------------------------------


def test_safe_published_id_accepts() -> None:
    pid = "pub_abcdef123456"
    assert safe_published_id(pid) == pid


@pytest.mark.parametrize(
    "value",
    [
        "",
        "pub_abcdef12345",  # 11 chars after prefix
        "pub_abcdef1234567",  # 13 chars after prefix
        "pub_ABCDEF123456",  # uppercase not allowed
        "p_abcdef123456",  # wrong prefix
        "pub-abcdef123456",  # wrong separator
        "PUB_abcdef123456",  # uppercase prefix
    ],
)
def test_safe_published_id_rejects(value: str) -> None:
    with pytest.raises(HTTPException) as ei:
        safe_published_id(value)
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# new_published_id
# ---------------------------------------------------------------------------


def test_new_published_id_shape() -> None:
    pid = new_published_id()
    assert re.fullmatch(r"pub_[a-z0-9]{12}", pid), pid


def test_new_published_id_unique() -> None:
    ids = {new_published_id() for _ in range(64)}
    assert len(ids) == 64


# ---------------------------------------------------------------------------
# published_path layout
# ---------------------------------------------------------------------------


def test_published_path_layout(tmp_path: Path) -> None:
    pid = "pub_abcdef123456"
    p = published_path(tmp_path, pid)
    assert p == tmp_path / "_published" / "pub_abcdef123456.json"


# ---------------------------------------------------------------------------
# paths.project_dir uses slug as folder name
# ---------------------------------------------------------------------------


def test_project_dir_keys_by_slug(tmp_path: Path) -> None:
    assert project_dir(tmp_path, "us-invoice") == tmp_path / "us-invoice"
    # Unicode slugs work too — the helper is just a path-join, validation
    # happens at the route layer.
    assert project_dir(tmp_path, "美国发票") == tmp_path / "美国发票"


# ---------------------------------------------------------------------------
# PidIndex CRUD round-trip
# ---------------------------------------------------------------------------


def _seed_project(workspace: Path, slug: str, pid: str) -> None:
    pdir = workspace / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "project.json").write_text(
        json.dumps({"project_id": pid, "slug": slug, "name": slug}),
        encoding="utf-8",
    )


def test_pid_index_register_resolve_unregister(tmp_path: Path) -> None:
    idx = PidIndex(tmp_path)
    assert idx.resolve_pid("p_aaaaaaaaaaaa") is None

    idx.register("p_aaaaaaaaaaaa", "us-invoice")
    assert idx.resolve_pid("p_aaaaaaaaaaaa") == "us-invoice"
    assert idx.resolve_slug("us-invoice") == "p_aaaaaaaaaaaa"

    idx.unregister("p_aaaaaaaaaaaa")
    assert idx.resolve_pid("p_aaaaaaaaaaaa") is None
    assert idx.resolve_slug("us-invoice") is None


def test_pid_index_rename(tmp_path: Path) -> None:
    idx = PidIndex(tmp_path)
    idx.register("p_aaaaaaaaaaaa", "old-slug")
    idx.rename("p_aaaaaaaaaaaa", "old-slug", "new-slug")
    assert idx.resolve_pid("p_aaaaaaaaaaaa") == "new-slug"
    assert idx.resolve_slug("new-slug") == "p_aaaaaaaaaaaa"
    assert idx.resolve_slug("old-slug") is None


def test_pid_index_bootstraps_from_disk(tmp_path: Path) -> None:
    _seed_project(tmp_path, "us-invoice", "p_aaaaaaaaaaaa")
    _seed_project(tmp_path, "美国发票", "p_bbbbbbbbbbbb")
    # Reserved underscored dirs and dotfiles should be skipped.
    (tmp_path / "_published").mkdir()
    (tmp_path / ".cache").mkdir()

    idx = PidIndex(tmp_path)
    assert idx.resolve_pid("p_aaaaaaaaaaaa") == "us-invoice"
    assert idx.resolve_pid("p_bbbbbbbbbbbb") == "美国发票"
    assert idx.resolve_slug("us-invoice") == "p_aaaaaaaaaaaa"


def test_pid_index_rescans_on_miss_when_workspace_changes(tmp_path: Path) -> None:
    idx = PidIndex(tmp_path)
    assert idx.resolve_pid("p_cccccccccccc") is None

    _seed_project(tmp_path, "fresh-project", "p_cccccccccccc")
    # Workspace dir mtime should have changed because we just created a child;
    # a miss must trigger a rescan rather than returning a stale None.
    assert idx.resolve_pid("p_cccccccccccc") == "fresh-project"
