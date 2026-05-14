"""Unit tests for the pre-project staging area.

Covers: stage_file allowlist/sniff, claim → real on-disk filename
(filesystem layout matches the regular upload_doc path: file at
`docs/<filename>`, sidecar at `docs/.meta/<filename>.json`), cleanup_stale
honours mtime.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.tools.projects import create_project
from app.workspace.paths import doc_meta_path, doc_path
from app.workspace.staging import (
    StagingClaimError,
    StagingError,
    claim_staged,
    cleanup_stale,
    stage_dir,
    stage_file,
    staging_root,
)


SAMPLE_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\nxref\n0 1\n0000000000 65535 f\n%%EOF\n"
PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


async def test_stage_file_writes_pdf(workspace: Path) -> None:
    info = await stage_file(workspace, SAMPLE_PDF, "invoice.pdf")
    assert info["filename"] == "invoice.pdf"
    assert info["ext"] == "pdf"
    assert info["size"] == len(SAMPLE_PDF)
    # PyMuPDF may return 0 for a degenerate test-fixture PDF — accept either.
    assert info["page_count"] >= 0
    token = info["stage_token"]
    assert isinstance(token, str) and token.startswith("st_")
    dirp = stage_dir(workspace, token)
    assert (dirp / "invoice.pdf").read_bytes() == SAMPLE_PDF


async def test_stage_file_writes_png(workspace: Path) -> None:
    info = await stage_file(workspace, PNG_HEADER, "scan.png")
    assert info["ext"] == "png"
    dirp = stage_dir(workspace, info["stage_token"])  # type: ignore[arg-type]
    assert (dirp / "scan.png").exists()


async def test_stage_file_rejects_unknown_extension(workspace: Path) -> None:
    with pytest.raises(StagingError, match="unsupported file type"):
        await stage_file(workspace, SAMPLE_PDF, "weird.docx")


async def test_stage_file_rejects_spoofed_extension(workspace: Path) -> None:
    """Same defence as upload_doc — magic-byte sniffing wins over filename."""
    with pytest.raises(StagingError, match="unsupported content"):
        await stage_file(workspace, b"<!doctype html><html>...", "image.png")


async def test_stage_file_rejects_directory_in_filename(workspace: Path) -> None:
    """A filename containing '/' must be stripped before we write — otherwise
    a malicious client could escape the stage dir."""
    info = await stage_file(workspace, SAMPLE_PDF, "../escaped.pdf")
    assert info["filename"] == "escaped.pdf"


async def test_claim_staged_moves_to_project(workspace: Path) -> None:
    """Claim routes through `upload_doc` → file lands at `docs/<filename>`,
    sidecar at `docs/.meta/<filename>.json` (the filename-native layout).
    No `d_xxx`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    info = await stage_file(workspace, SAMPLE_PDF, "invoice.pdf")
    token = info["stage_token"]
    filename = await claim_staged(workspace, token, pid)  # type: ignore[arg-type]
    # Post-dedupe filename echoed back — for a fresh project there is no
    # collision, so it should match the original.
    assert filename == "invoice.pdf"
    assert doc_path(workspace, pid, filename).read_bytes() == SAMPLE_PDF
    meta = json.loads(doc_meta_path(workspace, pid, filename).read_text())
    assert meta["filename"] == "invoice.pdf"
    assert meta["original_name"] == "invoice.pdf"
    # Staging dir is removed after a successful claim.
    assert not stage_dir(workspace, token).exists()  # type: ignore[arg-type]


async def test_claim_staged_unknown_token_raises(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(StagingClaimError):
        await claim_staged(workspace, "st_deadbeefdeadbeef", pid)


async def test_claim_staged_invalid_token_raises(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(StagingClaimError):
        await claim_staged(workspace, "../../../etc/passwd", pid)


async def test_cleanup_stale_removes_old_dirs_only(workspace: Path) -> None:
    """An aged staging dir is purged; a fresh one stays. cleanup_stale never
    touches non-staging children of the workspace root."""
    fresh = await stage_file(workspace, SAMPLE_PDF, "fresh.pdf")
    stale = await stage_file(workspace, SAMPLE_PDF, "stale.pdf")
    stale_dir = stage_dir(workspace, stale["stage_token"])  # type: ignore[arg-type]
    # Backdate the stale dir 48h.
    long_ago = time.time() - 48 * 3600
    import os
    os.utime(stale_dir, (long_ago, long_ago))

    removed = cleanup_stale(workspace, max_age_hours=24.0)
    assert removed == 1
    assert not stale_dir.exists()
    assert stage_dir(workspace, fresh["stage_token"]).exists()  # type: ignore[arg-type]


def test_cleanup_stale_noop_when_staging_root_missing(workspace: Path) -> None:
    """No staging activity yet — must be safe to call (app startup hook)."""
    assert not staging_root(workspace).exists()
    assert cleanup_stale(workspace) == 0
