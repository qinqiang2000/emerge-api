"""Per-page text-layer extraction (`app.tools.textlayer.extract_textlayer`).

Pins the four code paths:
- electronic PDF with real text → `scanned=False`, spans within page rect,
  `image_w/h` matches what `pdf_render_page` actually emits at 150dpi
- blank / image-only PDF → `scanned=True`, no spans
- second call hits the sidecar cache (no fitz re-open)
- PNG/JPG raster doc → `scanned=True`, `page_w/h == image_w/h` (pixel units)
- page out of range → `ValueError`
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import fitz
import pytest

from app.tools.docs import pdf_render_page, upload_doc
from app.tools.projects import create_project
from app.tools.textlayer import extract_textlayer
from app.workspace.paths import doc_textlayer_path


def _build_text_pdf(text: str = "Hello World, this is a long sentence.") -> bytes:
    """Single-page PDF with vector text. Long enough to clear the
    `_SCANNED_TEXT_THRESHOLD = 20` chars heuristic."""
    pdf = fitz.open()
    page = pdf.new_page()  # default A4: 595 x 842 pt
    page.insert_text((72, 72), text)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _build_blank_pdf() -> bytes:
    """Single-page PDF with NO text (and no embedded image) — fitz returns
    zero text blocks, the threshold heuristic flips `scanned=True`."""
    pdf = fitz.open()
    pdf.new_page()
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _build_png(w: int = 100, h: int = 100) -> bytes:
    """Plain raster PNG. `fitz.Pixmap(csRGB, IRect)` makes a solid colorimage
    we can ship via `upload_doc` (magic-byte sniff sees PNG)."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.clear_with(255)  # white
    return pix.tobytes("png")


async def test_extract_textlayer_electronic_pdf(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is False
    assert len(result["spans"]) >= 1
    joined = "".join(s["text"] for s in result["spans"])
    assert "Hello" in joined

    page_w = result["page_w"]
    page_h = result["page_h"]
    # A4 default page size at 72dpi point units.
    assert page_w == 595.0
    assert page_h == 842.0

    # All bboxes must fit on the page rect.
    for span in result["spans"]:
        x0, y0, x1, y1 = span["bbox"]
        assert 0 <= x0 <= page_w, span
        assert 0 <= x1 <= page_w, span
        assert 0 <= y0 <= page_h, span
        assert 0 <= y1 <= page_h, span

    # `_pixmap_dims` is asserted equivalent to the real pdf_render_page output
    # — this catches drift between the ceil-formula and fitz's actual pixmap
    # rounding (the in-code comment claims they agree at 150dpi; pin it).
    png_path = await pdf_render_page(workspace, pid, fname, page=1)
    real_pix = fitz.Pixmap(str(png_path))
    assert result["image_w"] == real_pix.width
    assert result["image_h"] == real_pix.height


async def test_extract_textlayer_scanned_pdf(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_blank_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "blank.pdf"))["filename"]

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is True
    assert result["spans"] == []
    assert result["page_w"] > 0
    assert result["page_h"] > 0


async def test_extract_textlayer_caches_sidecar(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    first = await extract_textlayer(workspace, pid, fname, page=1)

    sidecar = doc_textlayer_path(workspace, pid, fname, page=1)
    assert sidecar.exists(), "sidecar must be persisted after first call"

    # On the second call fitz.open MUST NOT be called — sidecar hit.
    import app.tools.textlayer as textlayer_mod

    def _boom(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("fitz.open called despite sidecar cache hit")

    # The fitz module is imported lazily inside the function. Patch on the
    # module that gets resolved at call time (fitz is `import fitz` inside
    # the func, so it lives on sys.modules['fitz']).
    import fitz as fitz_mod

    monkeypatch.setattr(fitz_mod, "open", _boom)

    second = await extract_textlayer(workspace, pid, fname, page=1)
    assert second == first


async def test_extract_textlayer_image_doc(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is True
    assert result["spans"] == []
    assert result["image_w"] == 100
    assert result["image_h"] == 100
    # For raster docs page_w/page_h collapse onto the pixel dims (see
    # docstring of `extract_textlayer`).
    assert result["page_w"] == 100.0
    assert result["page_h"] == 100.0


async def test_extract_textlayer_page_out_of_range(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    with pytest.raises(ValueError, match="out of range"):
        await extract_textlayer(workspace, pid, fname, page=999)


async def test_extract_textlayer_image_doc_page_out_of_range(
    workspace: Path,
) -> None:
    """PNG/JPG branch also enforces page=1 only."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png()
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    with pytest.raises(ValueError, match="out of range"):
        await extract_textlayer(workspace, pid, fname, page=2)
