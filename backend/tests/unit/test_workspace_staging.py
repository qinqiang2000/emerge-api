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
from app.workspace.paths import (
    chat_attachments_dir,
    doc_meta_path,
    doc_path,
    unbound_chat_attachments_dir,
)
from app.workspace.staging import (
    StagingClaimError,
    StagingError,
    claim_staged,
    claim_staged_to_chat,
    claim_staged_to_unbound_chat,
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
    assert info["kind"] == "doc"
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
    assert info["kind"] == "doc"
    dirp = stage_dir(workspace, info["stage_token"])  # type: ignore[arg-type]
    assert (dirp / "scan.png").exists()


async def test_stage_file_accepts_yaml_with_schema_kind(workspace: Path) -> None:
    """Phase B: yaml/yml are text-shaped → no magic-byte sniff, validated as
    UTF-8 only. Classified as `kind=schema` so the agent can route through
    `import_schema_from_yaml` after user confirm."""
    payload = b"- name: invoice_number\n  type: string\n  description: id\n"
    info = await stage_file(workspace, payload, "fields.yaml")
    assert info["filename"] == "fields.yaml"
    assert info["ext"] == "yaml"
    assert info["kind"] == "schema"
    assert info["size"] == len(payload)
    dirp = stage_dir(workspace, info["stage_token"])  # type: ignore[arg-type]
    assert (dirp / "fields.yaml").read_bytes() == payload


async def test_stage_file_accepts_csv_with_data_kind(workspace: Path) -> None:
    """csv → `kind=data` so the agent prompts before doing anything with it
    (no auto-import path yet)."""
    payload = b"col_a,col_b\n1,2\n3,4\n"
    info = await stage_file(workspace, payload, "samples.csv")
    assert info["ext"] == "csv"
    assert info["kind"] == "data"


async def test_stage_file_accepts_txt_with_note_kind(workspace: Path) -> None:
    payload = "user notes go here\nline 2\n".encode("utf-8")
    info = await stage_file(workspace, payload, "notes.txt")
    assert info["ext"] == "txt"
    assert info["kind"] == "note"


async def test_stage_file_accepts_md_with_note_kind(workspace: Path) -> None:
    payload = b"# heading\n\nsome notes\n"
    info = await stage_file(workspace, payload, "notes.md")
    assert info["ext"] == "md"
    assert info["kind"] == "note"


async def test_stage_file_classifies_schema_shaped_json_as_schema(workspace: Path) -> None:
    """JSON whose root is a list of `{name,type,...}` dicts is a schema
    candidate; anything else degrades to `note`."""
    schemaish = b'[{"name": "buyer_name", "type": "string", "description": "x"}]'
    info = await stage_file(workspace, schemaish, "fields.json")
    assert info["ext"] == "json"
    assert info["kind"] == "schema"

    plain_obj = b'{"foo": 1}'
    info2 = await stage_file(workspace, plain_obj, "config.json")
    assert info2["ext"] == "json"
    assert info2["kind"] == "note"


async def test_stage_file_rejects_oversize_text(workspace: Path) -> None:
    """256 KiB cap on text-shaped payloads — protects against someone
    accidentally dropping a multi-MB CSV thinking it's a small config."""
    too_big = b"a" * (256 * 1024 + 1)
    with pytest.raises(StagingError, match="oversize"):
        await stage_file(workspace, too_big, "huge.txt")


async def test_stage_file_rejects_non_utf8_text(workspace: Path) -> None:
    """The "looks textual" gate: invalid UTF-8 in a text-shaped extension
    fails fast rather than landing a binary blob with a `.txt` name."""
    with pytest.raises(StagingError, match="not valid UTF-8"):
        await stage_file(workspace, b"\xff\xfe\x00\x00binary", "fake.txt")


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


async def test_claim_staged_to_chat_moves_and_dedupes(workspace: Path) -> None:
    """Claim into chat scope: file lands at `chats/<chat_id>/attachments/<name>`
    with no sidecar; second claim under the same chat collides and dedupes."""
    pid = (await create_project(workspace, name="x"))["slug"]
    chat_id = "c_abc123def456"

    info1 = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    name1 = await claim_staged_to_chat(
        workspace, info1["stage_token"], pid, chat_id,
    )  # type: ignore[arg-type]
    assert name1 == "scan.pdf"
    att_dir = chat_attachments_dir(workspace, pid, chat_id)
    assert (att_dir / "scan.pdf").read_bytes() == SAMPLE_PDF
    # Chat claim must NOT pollute docs/ (create_project may have made the
    # empty dir, but no file should be inside).
    docs_d = workspace / pid / "docs"
    if docs_d.exists():
        assert [p.name for p in docs_d.iterdir() if p.is_file()] == []
    # No sidecar in chat scope.
    assert not (workspace / pid / "docs" / ".meta" / "scan.pdf.json").exists()

    info2 = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    name2 = await claim_staged_to_chat(
        workspace, info2["stage_token"], pid, chat_id,
    )  # type: ignore[arg-type]
    assert name2 == "scan (1).pdf"
    assert (att_dir / "scan (1).pdf").exists()
    # Staging dirs cleaned up.
    assert not stage_dir(workspace, info1["stage_token"]).exists()  # type: ignore[arg-type]
    assert not stage_dir(workspace, info2["stage_token"]).exists()  # type: ignore[arg-type]


async def test_claim_staged_to_chat_unknown_token_raises(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    with pytest.raises(StagingClaimError):
        await claim_staged_to_chat(
            workspace, "st_deadbeefdeadbeef", pid, "c_abc123def456",
        )


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


async def test_claim_staged_to_unbound_chat_moves_and_dedupes(workspace: Path) -> None:
    """Two staged files with the same name land under the unbound chat's
    attachments dir with `(1)` dedup suffix, mirroring `claim_staged_to_chat`.
    The staging dirs are wiped after the claim — leftover staged trees would
    leak storage and confuse `cleanup_stale`."""
    chat_id = "c_unb000111222"
    info1 = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")
    info2 = await stage_file(workspace, SAMPLE_PDF, "scan.pdf")

    name1 = await claim_staged_to_unbound_chat(
        workspace, info1["stage_token"], chat_id,  # type: ignore[arg-type]
    )
    assert name1 == "scan.pdf"
    att_dir = unbound_chat_attachments_dir(workspace, chat_id)
    assert (att_dir / "scan.pdf").exists()

    name2 = await claim_staged_to_unbound_chat(
        workspace, info2["stage_token"], chat_id,  # type: ignore[arg-type]
    )
    assert name2 == "scan (1).pdf"
    assert (att_dir / "scan (1).pdf").exists()

    # Staging dirs cleaned up.
    assert not stage_dir(workspace, info1["stage_token"]).exists()  # type: ignore[arg-type]
    assert not stage_dir(workspace, info2["stage_token"]).exists()  # type: ignore[arg-type]


async def test_claim_staged_to_unbound_chat_unknown_token_raises(workspace: Path) -> None:
    with pytest.raises(StagingClaimError):
        await claim_staged_to_unbound_chat(
            workspace, "st_deadbeefdeadbeef", "c_abc123def456",
        )
