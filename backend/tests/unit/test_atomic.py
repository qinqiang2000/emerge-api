import json
from pathlib import Path

import pytest

from app.workspace.atomic import (
    atomic_write_bytes,
    atomic_write_text,
    atomic_write_json,
)


def test_atomic_write_text_creates_file(workspace: Path) -> None:
    target = workspace / "x.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_overwrites(workspace: Path) -> None:
    target = workspace / "x.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_bytes(workspace: Path) -> None:
    target = workspace / "x.bin"
    atomic_write_bytes(target, b"\x00\x01\x02")
    assert target.read_bytes() == b"\x00\x01\x02"


def test_atomic_write_json_serializes(workspace: Path) -> None:
    target = workspace / "x.json"
    atomic_write_json(target, {"a": 1, "b": [2, 3]})
    assert json.loads(target.read_text()) == {"a": 1, "b": [2, 3]}


def test_atomic_write_creates_parent_dirs(workspace: Path) -> None:
    target = workspace / "deep" / "nested" / "x.json"
    atomic_write_json(target, {"k": "v"})
    assert target.exists()


def test_no_tmp_file_left_behind(workspace: Path) -> None:
    target = workspace / "x.json"
    atomic_write_json(target, {"k": 1})
    leftovers = [p for p in workspace.iterdir() if p.name.startswith(".")]
    assert leftovers == []
