"""`doc_to_blocks` — PDF rasterization fallback for providers that can't read
PDF natively (OpenAI-compatible `image_url` rejects raw PDF bytes).

Red lines under test:
  • `supports_pdf=True` (anthropic/google) → a single native `DocumentBlock`;
    no rasterization, so their behavior cannot regress.
  • `supports_pdf=False` → one `ImageBlock` per page, each preceded by an
    explicit `=== Page N ===` `TextBlock`. The markers are load-bearing: the
    grounding pass reports a 1-based `page` per value, and a bare image
    sequence carries no page signal.
  • non-PDF docs (image / text) are unaffected by the flag.
"""
from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest

from app.provider.base import DocumentBlock, ImageBlock, TextBlock
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.schema import doc_to_blocks


def _build_pdf(pages: int) -> bytes:
    pdf = fitz.open()
    for i in range(pages):
        page = pdf.new_page()
        page.insert_text((72, 72), f"page {i + 1} content")
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _build_png() -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40))
    return pix.tobytes("png")


async def test_pdf_native_stays_a_single_document_block(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _build_pdf(3), "doc.pdf"))["filename"]

    blocks = await doc_to_blocks(workspace, pid, fname, supports_pdf=True)

    assert len(blocks) == 1
    assert isinstance(blocks[0], DocumentBlock)
    assert blocks[0].media_type == "application/pdf"


async def test_pdf_rasterizes_one_image_per_page_with_page_markers(
    workspace: Path,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _build_pdf(3), "doc.pdf"))["filename"]

    blocks = await doc_to_blocks(workspace, pid, fname, supports_pdf=False)

    # 3 pages → [marker, image] * 3
    assert len(blocks) == 6
    for i in range(3):
        marker, image = blocks[2 * i], blocks[2 * i + 1]
        assert isinstance(marker, TextBlock)
        assert marker.text == f"=== Page {i + 1} ==="
        assert isinstance(image, ImageBlock)
        assert image.media_type == "image/png"
        assert image.data_b64


async def test_pdf_raster_respects_page_cap(workspace: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.tools.schema._MAX_RASTER_PAGES", 2)
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _build_pdf(5), "doc.pdf"))["filename"]

    blocks = await doc_to_blocks(workspace, pid, fname, supports_pdf=False)

    assert len(blocks) == 4  # 2 pages × (marker + image)
    assert blocks[-2].text == "=== Page 2 ==="


@pytest.mark.parametrize("supports_pdf", [True, False])
async def test_image_doc_unaffected_by_flag(workspace: Path, supports_pdf: bool) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, _build_png(), "shot.png"))["filename"]

    blocks = await doc_to_blocks(workspace, pid, fname, supports_pdf=supports_pdf)

    assert len(blocks) == 1
    assert isinstance(blocks[0], ImageBlock)


@pytest.mark.parametrize("supports_pdf", [True, False])
async def test_text_doc_unaffected_by_flag(workspace: Path, supports_pdf: bool) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, b'{"a": 1}', "d.json"))["filename"]

    blocks = await doc_to_blocks(workspace, pid, fname, supports_pdf=supports_pdf)

    assert len(blocks) == 1
    assert isinstance(blocks[0], TextBlock)
    assert blocks[0].text == '{"a": 1}'
