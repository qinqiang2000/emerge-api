"""Slug derivation + create_project / rename_project / list_projects coverage.

`derive_slug` is the single normalization point that turns a user-supplied
project name into the folder name (and `@`-mention handle). It MUST:
  * preserve Unicode (CJK, accents, emoji),
  * be filesystem-safe (no `/ \\ NUL` / control chars),
  * collapse whitespace into `-`,
  * never return an empty string (datestamp fallback),
  * truncate to 64 chars (the route-layer `safe_slug` cap).

Collisions are handled at create-time via `_ensure_unique_slug` (`-2`, `-3`,
…). Rename uses the same derivation so name and slug stay locked together —
a single concept exposed two ways."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.tools.projects import (
    create_project,
    derive_slug,
    list_projects,
    rename_project,
)
from app.workspace.pid_index import get_index


# ----- derive_slug pure-function coverage ---------------------------------


def test_derive_slug_kebab() -> None:
    assert derive_slug("Invoice Extraction") == "invoice-extraction"


def test_derive_slug_unicode() -> None:
    # CJK preserved verbatim; mixed CJK+Latin keeps the space-as-dash boundary.
    assert derive_slug("美国发票项目") == "美国发票项目"
    assert derive_slug("Q4 美国发票") == "q4-美国发票"


def test_derive_slug_fs_safe() -> None:
    # Slashes drop (not replaced with `-`) so paths can't be smuggled in.
    # NUL and other control chars are stripped entirely.
    assert derive_slug("foo/bar") == "foobar"
    assert derive_slug("\x00bad") == "bad"
    assert derive_slug("a\nb\tc") == "a-b-c"
    assert derive_slug("back\\slash") == "backslash"


def test_derive_slug_collapses_dashes() -> None:
    # Dashes only appear from whitespace runs; consecutive ones collapse and
    # leading/trailing trim so we never get `---foo---` on disk.
    assert derive_slug("---foo---bar---") == "foo-bar"
    assert derive_slug("foo  bar  baz") == "foo-bar-baz"


def test_derive_slug_truncates() -> None:
    name = "a" * 200
    slug = derive_slug(name)
    assert len(slug) == 64
    assert slug == "a" * 64


def test_derive_slug_empty_fallback() -> None:
    # All chars stripped → datestamp fallback so we still have a folder name.
    slug = derive_slug("////")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert re.fullmatch(rf"project-{today}-[0-9a-f]{{3}}", slug), slug


def test_derive_slug_non_string_input() -> None:
    # Defensive: tools handed a non-str shouldn't crash. Fallback applies.
    slug = derive_slug(None)  # type: ignore[arg-type]
    assert slug.startswith("project-")


# ----- create_project — collisions, pid registration, project.json -------


async def test_create_project_collision(workspace: Path) -> None:
    a = await create_project(workspace, name="foo")
    b = await create_project(workspace, name="foo")
    assert a["slug"] == "foo"
    assert b["slug"] == "foo-2"
    # Distinct pids — collisions only affect the folder handle.
    assert a["project_id"] != b["project_id"]
    assert (workspace / "foo").is_dir()
    assert (workspace / "foo-2").is_dir()


async def test_create_project_registers_pid_index(workspace: Path) -> None:
    out = await create_project(workspace, name="Inv MY")
    idx = get_index(workspace)
    assert idx.resolve_pid(out["project_id"]) == out["slug"]
    assert idx.resolve_slug(out["slug"]) == out["project_id"]


async def test_create_project_unicode_folder(workspace: Path) -> None:
    out = await create_project(workspace, name="美国发票项目")
    assert (workspace / "美国发票项目").is_dir()
    assert out["slug"] == "美国发票项目"


# ----- rename_project — atomic move, slug derivation, idempotence --------


async def test_rename_project_atomic(workspace: Path) -> None:
    a = await create_project(workspace, name="old name")
    old_slug = a["slug"]
    pid = a["project_id"]
    res = await rename_project(workspace, old_slug, new_slug="new-slug")
    assert res["slug"] == "new-slug"
    # Folder moved
    assert not (workspace / old_slug).exists()
    assert (workspace / "new-slug").is_dir()
    # project.json slug updated; pid stable
    blob = json.loads((workspace / "new-slug" / "project.json").read_text())
    assert blob["slug"] == "new-slug"
    assert blob["project_id"] == pid
    # pid_index repointed
    assert get_index(workspace).resolve_pid(pid) == "new-slug"


async def test_rename_project_by_name_only(workspace: Path) -> None:
    """`name` alone is enough — derive_slug runs and folder + name stay locked."""
    a = await create_project(workspace, name="Placeholder")
    old_slug = a["slug"]  # "placeholder"
    res = await rename_project(workspace, old_slug, name="马来 发票")
    new_slug = res["slug"]
    blob = json.loads((workspace / new_slug / "project.json").read_text())
    assert blob["slug"] == new_slug
    assert blob["name"] == "马来 发票"
    # derive_slug normalizes whitespace → "马来-发票"
    assert new_slug == "马来-发票"


async def test_rename_project_requires_arg(workspace: Path) -> None:
    a = await create_project(workspace, name="x")
    with pytest.raises(ValueError, match="new_slug.*name"):
        await rename_project(workspace, a["slug"])


async def test_rename_project_collision_suffix(workspace: Path) -> None:
    """Renaming into an existing slug-space picks `-2`."""
    a = await create_project(workspace, name="alpha")
    b = await create_project(workspace, name="beta")
    res = await rename_project(workspace, b["slug"], new_slug="alpha")
    assert res["slug"] == "alpha-2"


# ----- list_projects — slug field surface --------------------------------


async def test_list_projects_has_slug(workspace: Path) -> None:
    out = await create_project(workspace, name="Test One")
    items = await list_projects(workspace)
    assert len(items) == 1
    item = items[0]
    assert item["slug"] == out["slug"]
    assert item["project_id"] == out["project_id"]
    assert item["name"] == "Test One"
    # status flag still derived from prompt schema state.
    assert item["status"] in {"empty", "draft", "live"}
