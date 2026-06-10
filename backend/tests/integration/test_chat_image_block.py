"""`_load_image_blocks` reads from the right path based on attachment source.

`source='chat'` (default for paste/drop) → `chat_attachment_path`.
`source='docs'` (post-promote refs) → `doc_path`.
"""
from __future__ import annotations

import base64
from pathlib import Path

from app.chat.service import _load_image_blocks
from app.tools.projects import create_project
from app.workspace.paths import (
    chat_attachments_dir,
    docs_dir,
    docs_meta_dir,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
CID = "c_abc123def456"


async def test_image_block_reads_from_chat_attachment_path(workspace: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    att_dir = chat_attachments_dir(workspace, slug, CID)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "scan.png").write_bytes(PNG)

    blocks = _load_image_blocks(
        workspace, slug, CID,
        [{"filename": "scan.png", "source": "chat"}],
    )
    assert len(blocks) == 1
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(blocks[0]["source"]["data"]) == PNG


async def test_image_block_reads_from_docs_when_source_docs(workspace: Path) -> None:
    """Post-promote refs carry source='docs' and resolve via `doc_path`."""
    slug = (await create_project(workspace, name="x"))["slug"]
    docs_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    docs_meta_dir(workspace, slug).mkdir(parents=True, exist_ok=True)
    (docs_dir(workspace, slug) / "scan.png").write_bytes(PNG)

    blocks = _load_image_blocks(
        workspace, slug, CID,
        [{"filename": "scan.png", "source": "docs"}],
    )
    assert len(blocks) == 1
    assert base64.standard_b64decode(blocks[0]["source"]["data"]) == PNG


async def test_image_block_defaults_source_to_chat(workspace: Path) -> None:
    """Missing `source` field → treated as `chat`."""
    slug = (await create_project(workspace, name="x"))["slug"]
    att_dir = chat_attachments_dir(workspace, slug, CID)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "a.png").write_bytes(PNG)

    blocks = _load_image_blocks(workspace, slug, CID, [{"filename": "a.png"}])
    assert len(blocks) == 1


async def test_image_block_skips_missing_file(workspace: Path) -> None:
    slug = (await create_project(workspace, name="x"))["slug"]
    blocks = _load_image_blocks(
        workspace, slug, CID, [{"filename": "ghost.png", "source": "chat"}],
    )
    assert blocks == []


async def test_image_block_fits_oversized_attachment(workspace: Path) -> None:
    """User-attached images pass through `fit_image_for_agent` before being
    inlined — a 2400×3400 screenshot lands as a ≤1568px JPEG within the
    400KB SDK-boundary budget (2026-06-10 buffer fix). Small images (the
    other tests' tiny PNG stubs) are unaffected: fitting is conditional."""
    import fitz

    from app.tools.docs import _FIT_MAX_BYTES, _FIT_MAX_EDGE_PX

    big = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2400, 3400), False)
    big.clear_with(220)
    big_png = big.tobytes("png")

    slug = (await create_project(workspace, name="x"))["slug"]
    att_dir = chat_attachments_dir(workspace, slug, CID)
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "huge.png").write_bytes(big_png)

    blocks = _load_image_blocks(
        workspace, slug, CID, [{"filename": "huge.png", "source": "chat"}],
    )
    assert len(blocks) == 1
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    fitted = base64.standard_b64decode(blocks[0]["source"]["data"])
    assert len(fitted) <= _FIT_MAX_BYTES
    out = fitz.Pixmap(fitted)
    assert max(out.width, out.height) <= _FIT_MAX_EDGE_PX
