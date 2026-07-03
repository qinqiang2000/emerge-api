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
from app.tools.textlayer import (
    _looks_garbled,
    _span_is_garbled,
    extract_textlayer,
)
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
    # Pure-fitz pin: skip OCR so we don't need a provider stub here.
    # The partial-OCR merge path on electronic pages is exercised in
    # `test_extract_textlayer_electronic_pdf_merges_partial_ocr` below.
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    result = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )

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
    # Cache semantics are orthogonal to OCR routing — skip OCR on both
    # calls so this test doesn't depend on provider stubbing.
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    first = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )

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

    second = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )
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


async def test_extract_textlayer_text_doc_degrades_to_empty(workspace: Path) -> None:
    """Text-shaped docs (json/txt/md/…) have no visual layer — the textlayer
    call must short-circuit to an empty-spans payload, NOT try to `fitz.Pixmap`
    the raw bytes (which raises → 500 on the review-open textlayer fetch)."""
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, b'{"a": 3, "b": 4, "c": 12}', "mul.json"))["filename"]

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["text_source"] == "none"
    assert result["spans"] == []
    assert result["scanned"] is False
    assert result["ocr_attempted"] is False
    assert result["page_w"] == 0.0 and result["page_h"] == 0.0


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


async def test_extract_textlayer_electronic_pdf_merges_partial_ocr(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Electronic PDF + OCR returns one line whose center sits in a region
    fitz didn't cover (logo / outlined-path text on a real-world page).
    The OCR span is unioned with the fitz spans and `text_source` flips
    to `"fitz+ocr"`."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    # Pin fitz-only count by running once with skip_ocr=True (no provider
    # call), then start fresh under a different filename for the merge run
    # so we don't hit the sidecar cache from the first call.
    fitz_only = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )
    fitz_only_count = len(fitz_only["spans"])
    assert fitz_only_count >= 1
    # Wipe the sidecar so the merge call re-extracts.
    doc_textlayer_path(workspace, pid, fname, page=1).unlink()

    # OCR stub: one line near the top-left corner of an A4 page (page_w=595,
    # page_h=842). Bbox [10, 10, 200, 50] PDF-units is well above the fitz
    # text which starts at y=72. Gemini emits [y0,x0,y1,x1] normalised to
    # 0-1000, so to land at PDF coords (10,10)-(200,50):
    #   y0 = 10/842*1000  ≈ 11.875  → use 11
    #   x0 = 10/595*1000  ≈ 16.806  → use 16
    #   y1 = 50/842*1000  ≈ 59.382  → use 59
    #   x1 = 200/595*1000 ≈ 336.134 → use 336
    # The exact denormalised values will be close to [10, 10, 200, 50] but
    # we'll assert text + text_source rather than exact bbox equality.
    _install_provider(
        monkeypatch,
        return_value=_ocr_result([
            {"bbox": [11, 16, 59, 336], "text": "WAVEMAKER LOGO"},
        ]),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is False
    assert result["text_source"] == "fitz+ocr"
    # Fitz spans still present + the one new OCR span.
    assert len(result["spans"]) == fitz_only_count + 1
    texts = [s["text"] for s in result["spans"]]
    assert "WAVEMAKER LOGO" in texts


async def test_extract_textlayer_electronic_pdf_dedupes_ocr_overlap(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Electronic PDF + OCR returns a line whose bbox heavily overlaps
    an existing fitz span (IoU > 0.3) — dedupe drops it, `text_source`
    stays `"fitz"`, span count unchanged."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    # Get the fitz spans first (skip OCR, so no provider call yet).
    fitz_only = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )
    fitz_only_count = len(fitz_only["spans"])
    assert fitz_only_count >= 1

    # Emit an OCR line whose bbox is identical to the fitz span bbox
    # (IoU = 1.0 — far above the 0.3 dedupe threshold). Mirrors the real
    # Wavemaker-table case where OCR re-detects fitz-extracted numbers
    # with bbox shapes overlapping by ~50-100%.
    fx0, fy0, fx1, fy1 = fitz_only["spans"][0]["bbox"]
    # A4 = 595 x 842 pt.
    page_w, page_h = 595.0, 842.0
    # Normalise PDF-unit bbox → Gemini [y0, x0, y1, x1] 0-1000.
    y0_n = int(round(fy0 / page_h * 1000.0))
    x0_n = int(round(fx0 / page_w * 1000.0))
    y1_n = int(round(fy1 / page_h * 1000.0))
    x1_n = int(round(fx1 / page_w * 1000.0))

    # Wipe sidecar so the merge call re-runs.
    doc_textlayer_path(workspace, pid, fname, page=1).unlink()

    _install_provider(
        monkeypatch,
        return_value=_ocr_result([
            {"bbox": [y0_n, x0_n, y1_n, x1_n], "text": "duplicate of fitz"},
        ]),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["scanned"] is False
    # OCR ran but contributed 0 spans after dedupe → text_source stays "fitz".
    assert result["text_source"] == "fitz"
    assert len(result["spans"]) == fitz_only_count
    texts = [s["text"] for s in result["spans"]]
    assert "duplicate of fitz" not in texts


async def test_extract_textlayer_electronic_pdf_dedupes_text_and_line(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wavemaker-style table case: OCR's bbox for a number is shifted +
    narrower than fitz's, so IoU drops below 0.3 — but the text matches
    and both spans are on the same visual line. Text+Y-band rail must
    catch this; otherwise every table-cell number gets a ghost twin."""
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    fitz_only = await extract_textlayer(
        workspace, pid, fname, page=1, skip_ocr=True,
    )
    fitz_only_count = len(fitz_only["spans"])
    assert fitz_only_count >= 1

    fx0, fy0, fx1, fy1 = fitz_only["spans"][0]["bbox"]
    fitz_text = fitz_only["spans"][0]["text"]
    fw = fx1 - fx0
    fh = fy1 - fy0
    # OCR bbox: same text, same Y-band (slightly narrower vertically so
    # IoU isn't trivially high), shifted LEFT so the boxes barely overlap
    # — mirrors the real Wavemaker offset where IoU ≈ 0.09.
    page_w, page_h = 595.0, 842.0
    ox0 = max(0.0, fx0 - fw * 0.8)
    ox1 = fx0 + fw * 0.15
    oy0 = fy0 + fh * 0.1
    oy1 = fy1 - fh * 0.1
    y0_n = int(round(oy0 / page_h * 1000.0))
    x0_n = int(round(ox0 / page_w * 1000.0))
    y1_n = int(round(oy1 / page_h * 1000.0))
    x1_n = int(round(ox1 / page_w * 1000.0))

    doc_textlayer_path(workspace, pid, fname, page=1).unlink()

    _install_provider(
        monkeypatch,
        return_value=_ocr_result([
            {"bbox": [y0_n, x0_n, y1_n, x1_n], "text": fitz_text},
        ]),
    )

    result = await extract_textlayer(workspace, pid, fname, page=1)

    assert result["text_source"] == "fitz"
    assert len(result["spans"]) == fitz_only_count


# ── Garbled-CJK guard (CID font, no ToUnicode) ────────────────────────────
#
# A PDF whose CJK font is a Type0/Identity-H subset with no ToUnicode CMap
# makes fitz emit CID glyph indices reinterpreted as Unicode — garbage like
# "㘞ỻ㋗匉☐" where "晶振芯片" should be. The strings below are verbatim from
# such a real document (金进科技--TP25004430.pdf). The guard must drop these
# while leaving real Chinese, Latin, and numbers untouched.

# Verbatim garbled lines from the real doc — must all be flagged.
_GARBLED_SAMPLES = [
    "㘞ỻ㋗匉☐ġġġ",
    "㶙⛛ⶪ㘞䥹搓⭆᷂㚱旸℔⎠",
    "慹徃䥹㈨ĩ㶙⛛Ī㚱旸℔⎠",
    "ıĸĶĶġĹĵķĶġĵķĲĲ↮㛢ĶĶı",
    "ࢋⴽ١ߓॠ操ؘЏ߄ஒҸ՛",  # Microsoft YaHei garbage (Devanagari-ish)
]

# Must NEVER be flagged — well-formed Chinese / Latin / numbers / mixed.
_CLEAN_SAMPLES = [
    "金进科技(深圳)有限公司",
    "深圳市晶科鑫实业有限公司",
    "广东省深圳市龙岗区平湖街道山厦社区内环路5号",
    "采购订单识别：发票号",          # with fullwidth colon
    "PURCHASE ORDER",
    "TP25004430",
    "12,000.000",
    "Crystal oscillator 12M/3225",
]


@pytest.mark.parametrize("text", _GARBLED_SAMPLES)
def test_looks_garbled_flags_cid_garbage(text: str) -> None:
    assert _looks_garbled(text) is True


@pytest.mark.parametrize("text", _CLEAN_SAMPLES)
def test_looks_garbled_passes_real_text(text: str) -> None:
    assert _looks_garbled(text) is False


def test_span_is_garbled_requires_suspect_font() -> None:
    """Both signals must fire: garbled text alone (no suspect font) is kept,
    so legit rare-character content on a healthy font is never dropped."""
    garbled = {"font": "PMingLiU", "text": "㘞ỻ㋗匉☐"}
    # Signal 1 absent (empty suspect set) → keep even though text looks bad.
    assert _span_is_garbled(garbled, set()) is False
    # Signal 1 present but font not in the suspect set → keep.
    assert _span_is_garbled(garbled, {"SomeOtherFont"}) is False
    # Both signals present → drop.
    assert _span_is_garbled(garbled, {"PMingLiU"}) is True


def test_span_is_garbled_keeps_recovered_cjk_on_suspect_font() -> None:
    """A suspect CID font whose text fitz DID recover correctly (real Chinese)
    must survive — guards against regressing normal PDFs that merely share the
    no-ToUnicode font shape."""
    good = {"font": "PMingLiU", "text": "金进科技有限公司"}
    assert _span_is_garbled(good, {"PMingLiU"}) is False


def test_span_is_garbled_keeps_latin_on_suspect_font() -> None:
    """WinAnsi siblings share the basefont NAME with the broken Identity-H
    variant, so a Latin-only span can carry a suspect font name — its lack of
    non-ASCII chars must keep it (numbers/English never garble)."""
    latin = {"font": "Microsoft YaHei", "text": "TP25004430"}
    assert _span_is_garbled(latin, {"Microsoft YaHei"}) is False
