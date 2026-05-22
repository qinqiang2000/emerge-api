"""Per-page document translation (`app.tools.translate.translate_page`).

Pins:
- textlayer-mode branch: spans from sidecar → text-only prompt → bbox in PDF
  units copied from the sidecar, length-checked against translator output
- vision-mode branch: scanned/image doc → ImageBlock attached → bbox
  denormalised from Gemini's `[y0,x0,y1,x1]` 0–1000 back to PDF page units
- cache hit on (filename, page, target_lang, mode, model_id)
- `force_refresh=True` bypasses cache
- different `model_id` ⇒ separate cache entries (both miss on the first call)
- textlayer-mode tolerates missing/extra items by aligning by `index`; missing
  indices fall back to the original text so the page still renders

Provider is monkeypatched via `app.tools.translate.get_provider_for_model`
so no real HTTP / no real LLM is touched.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import fitz
import pytest

from app.provider.base import ImageBlock, ProviderResult, TextBlock
from app.tools.docs import upload_doc
from app.tools.projects import create_project
from app.tools.translate import translate_page
from app.workspace.paths import (
    doc_translate_dir,
    doc_translate_path,
)


_DEFAULT_TRANSLATE_MODEL = "gemini-flash-lite-latest"


def _build_text_pdf(text: str = "Hello World, this is a long sentence.") -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _build_png(w: int = 100, h: int = 100) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h))
    pix.clear_with(255)
    return pix.tobytes("png")


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    *,
    return_value: ProviderResult | None = None,
) -> AsyncMock:
    """Monkeypatch `get_provider_for_model` in the translate module to a
    stub Provider. Returns the AsyncMock for assertion on `extract` calls."""
    stub = AsyncMock()
    if return_value is not None:
        stub.extract = AsyncMock(return_value=return_value)
    else:
        stub.extract = AsyncMock()
    monkeypatch.setattr(
        "app.tools.translate.get_provider_for_model",
        lambda model_id, **_kw: stub,
    )
    return stub


def _result(payload: dict[str, Any], model_id: str = _DEFAULT_TRANSLATE_MODEL) -> ProviderResult:
    return ProviderResult(
        raw_json=payload, model_id=model_id, input_tokens=10, output_tokens=20,
    )


async def test_translate_page_textlayer_mode(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    # The synthetic PDF emits a single span "Hello World, this is a long
    # sentence." — translator must return ONE item to match.
    from app.tools.textlayer import extract_textlayer

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n_spans = len(sidecar["spans"])
    assert n_spans >= 1, "fixture must have at least one span"

    translations = [{"index": i, "translated": f"你好{i}"} for i in range(n_spans)]
    # `raw_json` is typed dict in ProviderResult, and translate.py accepts
    # single-key-dict wrap of the array (see translate.py lines 254-259).
    stub = _install_provider(
        monkeypatch, return_value=_result({"items": translations}),
    )

    result = await translate_page(workspace, pid, fname, page=1)

    assert result["mode"] == "textlayer"
    assert result["model_id"] == _DEFAULT_TRANSLATE_MODEL
    assert len(result["lines"]) == n_spans
    assert stub.extract.await_count == 1

    # Each line carries the sidecar's PDF-unit bbox and the original span text.
    for i, span in enumerate(sidecar["spans"]):
        assert result["lines"][i]["bbox"] == [float(v) for v in span["bbox"]]
        assert result["lines"][i]["original"] == span["text"]
        assert result["lines"][i]["translated"] == f"你好{i}"

    # textlayer-mode user_content must be TEXT-ONLY (no ImageBlock — that
    # would force a vision call and defeat the cheap text-only branch).
    call = stub.extract.await_args
    user_content = call.kwargs["user_content"]
    assert all(isinstance(b, TextBlock) for b in user_content), (
        f"textlayer mode leaked a non-text block: {[type(b).__name__ for b in user_content]}"
    )


async def test_translate_page_vision_mode(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    png_bytes = _build_png(w=100, h=100)
    fname = (await upload_doc(workspace, pid, png_bytes, "scan.png"))["filename"]

    # Gemini returns normalised [y0, x0, y1, x1] in 0–1000. For a 100×100
    # image:
    #   y0=100 / 1000 * page_h(100) = 10.0  → pdf_y0
    #   x0=200 / 1000 * page_w(100) = 20.0  → pdf_x0
    #   y1=300 / 1000 * page_h(100) = 30.0  → pdf_y1
    #   x1=400 / 1000 * page_w(100) = 40.0  → pdf_x1
    # `_denormalise_bbox` returns `[x0, y0, x1, y1]` → [20, 10, 40, 30].
    stub = _install_provider(
        monkeypatch,
        return_value=_result({
            "lines": [
                {
                    "bbox": [100, 200, 300, 400],
                    "original": "Hola",
                    "translated": "你好",
                },
            ],
        }),
    )

    result = await translate_page(workspace, pid, fname, page=1)

    assert result["mode"] == "vision"
    assert len(result["lines"]) == 1
    assert result["lines"][0]["bbox"] == [20.0, 10.0, 40.0, 30.0]
    assert result["lines"][0]["original"] == "Hola"
    assert result["lines"][0]["translated"] == "你好"

    # Vision mode must attach at least one ImageBlock.
    call = stub.extract.await_args
    user_content = call.kwargs["user_content"]
    assert any(isinstance(b, ImageBlock) for b in user_content), (
        f"vision mode missing ImageBlock: {[type(b).__name__ for b in user_content]}"
    )


async def test_translate_page_cache_hit(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    from app.tools.textlayer import extract_textlayer

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n_spans = len(sidecar["spans"])
    translations = [{"index": i, "translated": f"翻{i}"} for i in range(n_spans)]
    stub = _install_provider(
        monkeypatch, return_value=_result({"items": translations}),
    )

    first = await translate_page(workspace, pid, fname, page=1)
    assert stub.extract.await_count == 1

    cache_path = doc_translate_path(
        workspace, pid, fname,
        page=1, target_lang="zh", mode="textlayer",
        model_id=_DEFAULT_TRANSLATE_MODEL,
    )
    assert cache_path.exists()

    second = await translate_page(workspace, pid, fname, page=1)
    # Provider NOT called again — same payload returned from disk.
    assert stub.extract.await_count == 1
    assert second == first


async def test_translate_page_force_refresh_bypasses_cache(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    from app.tools.textlayer import extract_textlayer

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n_spans = len(sidecar["spans"])
    translations = [{"index": i, "translated": f"翻{i}"} for i in range(n_spans)]
    stub = _install_provider(
        monkeypatch, return_value=_result({"items": translations}),
    )

    await translate_page(workspace, pid, fname, page=1)
    assert stub.extract.await_count == 1

    # Same key, but force_refresh=True must skip the cache read.
    await translate_page(
        workspace, pid, fname, page=1, force_refresh=True,
    )
    assert stub.extract.await_count == 2


async def test_translate_page_model_id_in_cache_key(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    pid = (await create_project(workspace, name="x"))["slug"]
    pdf_bytes = _build_text_pdf()
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    from app.tools.textlayer import extract_textlayer

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n_spans = len(sidecar["spans"])
    translations = [{"index": i, "translated": f"翻{i}"} for i in range(n_spans)]
    stub = _install_provider(
        monkeypatch, return_value=_result({"items": translations}),
    )

    # Two distinct model ids — both must miss the cache on first call.
    await translate_page(
        workspace, pid, fname, page=1, model_id="gemini-2.5-flash",
    )
    await translate_page(
        workspace, pid, fname, page=1, model_id="gemini-3.5-flash",
    )
    assert stub.extract.await_count == 2

    # Both cache files coexist under the per-doc _translate dir.
    cache_dir = doc_translate_dir(workspace, pid, fname)
    files = sorted(p.name for p in cache_dir.iterdir())
    assert any("gemini-2.5-flash" in f for f in files), files
    assert any("gemini-3.5-flash" in f for f in files), files


async def test_translate_page_textlayer_alignment_by_index_fills_gaps(
    workspace: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Translator may merge / drop / reorder items under length pressure.
    Alignment-by-index keeps the page rendering: covered indices get the
    translation, missing indices fall back to the original span text."""
    # Build a multi-span PDF (two long lines, total > 20 chars so the page
    # is classified as electronic, not scanned).
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Hello world this is the first line.")
    page.insert_text((72, 120), "Bonjour world this is the second line.")
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    pdf_bytes = buf.getvalue()
    pid = (await create_project(workspace, name="x"))["slug"]
    fname = (await upload_doc(workspace, pid, pdf_bytes, "doc.pdf"))["filename"]

    from app.tools.textlayer import extract_textlayer

    sidecar = await extract_textlayer(workspace, pid, fname, page=1)
    n_spans = len(sidecar["spans"])
    assert n_spans >= 2, "fixture must have at least two spans for this test"

    # Translator omits the LAST item (a common LLM failure mode).
    partial = [
        {"index": i, "translated": f"翻{i}"}
        for i in range(n_spans - 1)
    ]
    _install_provider(
        monkeypatch, return_value=_result({"items": partial}),
    )

    result = await translate_page(workspace, pid, fname, page=1)

    assert len(result["lines"]) == n_spans
    # Covered indices got translated; the last one fell back to original.
    for i, span in enumerate(sidecar["spans"]):
        original = span["text"]
        if i < n_spans - 1:
            assert result["lines"][i]["translated"] == f"翻{i}"
        else:
            assert result["lines"][i]["translated"] == original
        assert result["lines"][i]["original"] == original

    # Cache IS written — partial translation is still a valid payload.
    cache_path = doc_translate_path(
        workspace, pid, fname,
        page=1, target_lang="zh", mode="textlayer",
        model_id=_DEFAULT_TRANSLATE_MODEL,
    )
    assert cache_path.exists()
