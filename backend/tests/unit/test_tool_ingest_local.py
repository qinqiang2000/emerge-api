"""Unit tests for `app.tools.docs.ingest_local_path`.

Pins:
- happy path (directory of mixed pdf/png/junk → only pdf/png land in docs)
- allowlist rejection (resolved path outside roots)
- symlink-escape rejection (allowed-root/symlink → /etc → reject)
- max_files cap
- attachments target writes to chats/<cid>/attachments/, not docs/
- single-file path supported
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.tools.docs import IngestLocalError, ingest_local_path
from app.tools.projects import create_project


SAMPLE_PDF = b"%PDF-1.4\n%%EOF\n"
SAMPLE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SAMPLE_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


async def test_ingest_dir_into_docs(workspace: Path, tmp_path: Path) -> None:
    src = tmp_path / "scans"
    src.mkdir()
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    (src / "b.png").write_bytes(SAMPLE_PNG)
    (src / "notes.txt").write_bytes(b"hello world")  # text docs now ingest too
    (src / "junk.bin").write_bytes(b"\x00\x01\x02binary")  # genuinely unsupported
    slug = (await create_project(workspace, name="x"))["slug"]

    out = await ingest_local_path(
        workspace, slug, str(src), allowlist=(tmp_path.resolve(),),
    )
    assert {f["filename"] for f in out["ingested"]} == {"a.pdf", "b.png", "notes.txt"}
    assert out["skipped"] == [{"name": "junk.bin", "reason": "not pdf/png/jpg or utf-8 text"}]
    assert out["errors"] == []
    assert (workspace / slug / "docs" / "a.pdf").read_bytes() == SAMPLE_PDF
    assert (workspace / slug / "docs" / "notes.txt").read_bytes() == b"hello world"


async def test_ingest_single_file_path(workspace: Path, tmp_path: Path) -> None:
    src = tmp_path / "lone.pdf"
    src.write_bytes(SAMPLE_PDF)
    slug = (await create_project(workspace, name="x"))["slug"]
    out = await ingest_local_path(
        workspace, slug, str(src), allowlist=(tmp_path.resolve(),),
    )
    assert [f["filename"] for f in out["ingested"]] == ["lone.pdf"]


async def test_ingest_rejects_path_outside_allowlist(
    workspace: Path, tmp_path: Path,
) -> None:
    """Tightest allowlist (a sibling dir) → tmp_path is outside → reject."""
    src = tmp_path / "scans"
    src.mkdir()
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    sibling = tmp_path / "elsewhere"
    sibling.mkdir()
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="outside the ingest allowlist"):
        await ingest_local_path(
            workspace, slug, str(src), allowlist=(sibling.resolve(),),
        )


async def test_ingest_rejects_symlink_escape(
    workspace: Path, tmp_path: Path,
) -> None:
    """A symlink inside the allowed root that points outside MUST be caught.
    We resolve before checking the prefix so the link can't smuggle /etc in."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(SAMPLE_PDF)
    link = allowed / "link"
    os.symlink(outside, link)
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="outside the ingest allowlist"):
        await ingest_local_path(
            workspace, slug, str(link), allowlist=(allowed.resolve(),),
        )


async def test_ingest_max_files_cap(workspace: Path, tmp_path: Path) -> None:
    src = tmp_path / "many"
    src.mkdir()
    for i in range(5):
        (src / f"f{i}.pdf").write_bytes(SAMPLE_PDF)
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="too many files"):
        await ingest_local_path(
            workspace, slug, str(src),
            allowlist=(tmp_path.resolve(),), max_files=3,
        )


async def test_ingest_attachments_target(
    workspace: Path, tmp_path: Path,
) -> None:
    src = tmp_path / "drop"
    src.mkdir()
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    slug = (await create_project(workspace, name="x"))["slug"]
    out = await ingest_local_path(
        workspace, slug, str(src),
        allowlist=(tmp_path.resolve(),),
        target="attachments",
        chat_id="c_abc123def456",
    )
    assert [f["filename"] for f in out["ingested"]] == ["a.pdf"]
    assert (
        workspace / slug / "chats" / "c_abc123def456" / "attachments" / "a.pdf"
    ).read_bytes() == SAMPLE_PDF
    # docs/ stays empty.
    assert not (workspace / slug / "docs" / "a.pdf").exists()


async def test_ingest_attachments_requires_chat_id(
    workspace: Path, tmp_path: Path,
) -> None:
    src = tmp_path / "drop"
    src.mkdir()
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="requires chat_id"):
        await ingest_local_path(
            workspace, slug, str(src),
            allowlist=(tmp_path.resolve(),),
            target="attachments",
        )


async def test_ingest_recursive_walks_subdirs(
    workspace: Path, tmp_path: Path,
) -> None:
    src = tmp_path / "tree"
    (src / "sub").mkdir(parents=True)
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    (src / "sub" / "b.jpg").write_bytes(SAMPLE_JPG)
    slug = (await create_project(workspace, name="x"))["slug"]
    out = await ingest_local_path(
        workspace, slug, str(src),
        allowlist=(tmp_path.resolve(),), recursive=True,
    )
    names = {f["filename"] for f in out["ingested"]}
    assert names == {"a.pdf", "b.jpg"}


async def test_ingest_nonrecursive_skips_subdirs(
    workspace: Path, tmp_path: Path,
) -> None:
    src = tmp_path / "tree"
    (src / "sub").mkdir(parents=True)
    (src / "a.pdf").write_bytes(SAMPLE_PDF)
    (src / "sub" / "b.jpg").write_bytes(SAMPLE_JPG)
    slug = (await create_project(workspace, name="x"))["slug"]
    out = await ingest_local_path(
        workspace, slug, str(src), allowlist=(tmp_path.resolve(),),
    )
    names = {f["filename"] for f in out["ingested"]}
    assert names == {"a.pdf"}


async def test_ingest_bad_target_value(workspace: Path, tmp_path: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="target must be"):
        await ingest_local_path(
            workspace, slug, str(tmp_path),
            allowlist=(tmp_path.resolve(),), target="bogus",
        )


async def test_ingest_missing_path(workspace: Path, tmp_path: Path) -> None:
    ghost = tmp_path / "does-not-exist"
    slug = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(IngestLocalError, match="does not exist"):
        await ingest_local_path(
            workspace, slug, str(ghost), allowlist=(tmp_path.resolve(),),
        )
