"""Per-page text-layer extraction (`app.tools.textlayer.extract_textlayer`).

Pins the code paths:
- electronic PDF with real text → `scanned=False`, `text_source="fitz"`,
  spans within page rect, `image_w/h` matches what `pdf_render_page`
  actually emits at 150dpi
- blank / image-only PDF, `skip_ocr=True` → `scanned=True`,
  `text_source="none"`, no spans (no OCR call)
- second call hits the sidecar cache (no fitz re-open)
- PNG/JPG raster doc, `skip_ocr=True` → `scanned=True`,
  `text_source="none"`, `page_w/h == image_w/h` (pixel units)
- page out of range → `ValueError`
- OCR fallback (PNG / scanned PDF, default `skip_ocr=False`) calls the
  provider; spans / `text_source` reflect provider output; provider
  errors cache an empty payload so we don't retry; `skip_ocr=True`
  bypasses provider entirely.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import fitz
import pytest

from app.provider.base import ProviderResult
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


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_value: ProviderResult | None = None,
    raises: Exception | None = None,
) -> AsyncMock:
    """Monkeypatch `get_provider_for_model` in the textlayer module to a
    stub Provider. Returns the AsyncMock for assertion on `extract` calls.

    Mirrors the `_install_provider` pattern in `test_translate.py`, adapted
    for the textlayer module's import path (textlayer imports
    `get_provider_for_model` locally inside `_ocr_extract_spans`, so we
    patch `app.provider.get_provider_for_model` — the symbol that the
    function-local `from app.provider import get_provider_for_model`
    resolves to)."""
    stub = AsyncMock()
    if raises is not None:
        stub.extract = AsyncMock(side_effect=raises)
    elif return_value is not None:
        stub.extract = AsyncMock(return_value=return_value)
    else:
        stub.extract = AsyncMock()
    monkeypatch.setattr(
        "app.provider.get_provider_for_model",
        lambda model_id, **_kw: stub,
    )
    return stub


def _ocr_result(lines: list[dict[str, Any]]) -> ProviderResult:
    """Wrap OCR lines as a ProviderResult — root must be `dict` (the
    OCR response schema has `lines` under an object root)."""
    return ProviderResult(
        raw_json={"lines": lines},
        model_id="gemini-flash-lite-latest",
        input_tokens=10,
        output_tokens=20,
    )


async def test_extract_textlayer_electronic_pdf(workspace: Path) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is False
    assert result["text_source"] == "fitz"
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


async def test_extract_textlayer_scanned_pdf_skip_ocr(workspace: Path) -> None:
    """`skip_ocr=True` — fitz returns nothing, OCR bypassed, sidecar
    records `text_source="none"`. Pins the no-LLM path."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_blank_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "blank.pdf"))["filename"]

    result = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )

    assert result["scanned"] is True
    assert result["text_source"] == "none"
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
    import app.tools.textlayer as textlayer_mod  # noqa: F401 — used for import side-effect

    def _boom(*args, **kwargs):  # pragma: no cover - guard
        raise AssertionError("fitz.open called despite sidecar cache hit")

    # The fitz module is imported lazily inside the function. Patch on the
    # module that gets resolved at call time (fitz is `import fitz` inside
    # the func, so it lives on sys.modules['fitz']).
    import fitz as fitz_mod

    monkeypatch.setattr(fitz_mod, "open", _boom)

    second = await extract_textlayer(workspace, pid, fname, page=1)
    assert second == first


async def test_extract_textlayer_image_doc_skip_ocr(workspace: Path) -> None:
    """PNG with `skip_ocr=True` — provider never called, sidecar records
    `text_source="none"` so the frontend honestly degrades."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    result = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )

    assert result["scanned"] is True
    assert result["text_source"] == "none"
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


# ---------------------------------------------------------------------------
# OCR fallback tests — provider mocked so no real LLM is touched.
# ---------------------------------------------------------------------------


async def test_extract_textlayer_image_doc_invokes_ocr(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PNG fixture, mock provider returns one OCR line, assert spans
    populated, `text_source == "ocr"`, bbox denormalised correctly."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    # Gemini returns [y0, x0, y1, x1] normalised to 0–1000. For a 100×100
    # image (page_w=page_h=100):
    #   y0=100/1000*100 = 10  → pdf_y0
    #   x0=200/1000*100 = 20  → pdf_x0
    #   y1=300/1000*100 = 30  → pdf_y1
    #   x1=400/1000*100 = 40  → pdf_x1
    # The helper emits `[x0, y0, x1, y1]` → [20, 10, 40, 30].
    stub = _install_provider(
        monkeypatch,
        return_value=_ocr_result([
            {"bbox": [100, 200, 300, 400], "text": "Hello PNG"},
        ]),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is True
    assert result["text_source"] == "ocr"
    assert len(result["spans"]) == 1
    span = result["spans"][0]
    assert span["bbox"] == [20.0, 10.0, 40.0, 30.0]
    assert span["text"] == "Hello PNG"
    # font_size is derived from bbox HEIGHT × 0.85 (see textlayer.py
    # `_ocr_extract_spans`); for a 20px-tall bbox that's 17.0px.
    assert span["font_size"] == pytest.approx(20.0 * 0.85)

    # Exactly one OCR call.
    assert stub.extract.await_count == 1


async def test_extract_textlayer_image_doc_ocr_failure_caches_empty(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PNG fixture, provider raises — sidecar IS still written with
    `text_source="none"` and `spans=[]` so subsequent calls don't
    re-attempt the LLM (otherwise every overlay open would slam the
    provider on a flaky network)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    stub = _install_provider(
        monkeypatch, raises=RuntimeError("provider exploded"),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is True
    assert result["text_source"] == "none"
    assert result["spans"] == []

    # Sidecar persisted so the next call hits disk, not the provider.
    sidecar = doc_textlayer_path(workspace, pid, fname, page=1)
    assert sidecar.exists()

    cached = json.loads(sidecar.read_text())
    assert cached["text_source"] == "none"
    assert cached["spans"] == []

    # Second call must hit the cache — provider NOT called again.
    assert stub.extract.await_count == 1
    second = await extract_textlayer(workspace, pid, fname, page=1)
    assert stub.extract.await_count == 1
    assert second == result


async def test_extract_textlayer_scanned_pdf_invokes_ocr(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank PDF (fitz `scanned=True` heuristic kicks in), provider mocked
    to return one OCR line — spans populated, `text_source="ocr"`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_blank_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "blank.pdf"))["filename"]

    stub = _install_provider(
        monkeypatch,
        return_value=_ocr_result([
            {"bbox": [50, 100, 150, 200], "text": "Found via OCR"},
        ]),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is True
    assert result["text_source"] == "ocr"
    assert len(result["spans"]) == 1
    assert result["spans"][0]["text"] == "Found via OCR"
    # bbox stays in PDF point units (A4 = 595×842), not pixel units.
    page_w = result["page_w"]
    page_h = result["page_h"]
    expected = [
        (100 / 1000.0) * page_w,
        (50 / 1000.0) * page_h,
        (200 / 1000.0) * page_w,
        (150 / 1000.0) * page_h,
    ]
    assert result["spans"][0]["bbox"] == expected
    assert stub.extract.await_count == 1


async def test_extract_textlayer_skip_ocr_bypasses_provider(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`skip_ocr=True` — provider MUST NOT be called even when the page
    would otherwise trigger the OCR fallback. Used by tests / cost-sensitive
    callers."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    stub = _install_provider(monkeypatch)  # never expected to be awaited

    result = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )

    assert result["text_source"] == "none"
    assert result["spans"] == []
    assert stub.extract.await_count == 0


async def test_extract_textlayer_ocr_malformed_payload_caches_empty(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider returns a non-list `lines` key — sidecar caches empty
    spans rather than blowing up, so a misbehaving provider can't
    permanently 500 the review overlay."""
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    bad_result = ProviderResult(
        raw_json={"lines": "not actually a list"},
        model_id="gemini-flash-lite-latest",
        input_tokens=0,
        output_tokens=0,
    )
    _install_provider(monkeypatch, return_value=bad_result)

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["text_source"] == "none"
    assert result["spans"] == []
