"""PDF text-layer extraction (review-mode UX only).

Drives the transparent text overlay that lets users select + copy the
original text on top of the rasterised PDF page that `pdf_render_page`
produces. The extraction reads fitz's vector text via `get_text("dict")`
and persists a per-page sidecar so subsequent calls hit disk, mirroring the
lazy + atomic pattern of `pdf_render_page`.

When fitz returns nothing usable (image doc or scanned PDF), we fall back
to a Gemini vision OCR call so the frontend overlay still has spans to
hang selection on. OCR result is persisted in the same sidecar so
subsequent calls hit disk — provider failure caches an empty payload so
we don't hammer the provider on every open.

Hard rules this respects:
- bbox / coordinates are NEVER fed back into the extract or runtime prompt
  path. The sidecar is consumed by the frontend review overlay only.
- No image few-shot; this module touches neither extract nor labeler.
  The OCR-only prompt below is review-UX scaffolding, not few-shot.
- Scanned-PDF / image-doc pages still record `scanned=true`; the new
  `text_source` field tells callers WHERE the spans came from (`fitz`,
  `ocr`, or `none` = OCR was attempted but yielded zero spans, or was
  explicitly skipped via `skip_ocr=True`).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from app.workspace.atomic import atomic_write_text
from app.workspace.paths import (
    doc_meta_path,
    doc_path,
    doc_textlayer_dir,
    doc_textlayer_path,
)


# Page is considered scanned when fitz returns less than this much text.
# Mirrors the threshold called out in the plan (`docs/superpowers/plans/
# whimsical-knitting-lantern.md`): below 20 chars → assume embedded raster.
_SCANNED_TEXT_THRESHOLD = 20

# Render dpi used by `pdf_render_page` — keep in lockstep so `image_w/h`
# reported here match the PNG the frontend will load.
_RENDER_DPI = 150


# OCR fallback — schema + prompt. Mirrors translate.py:_VISION_RESPONSE_SCHEMA
# but without the `translated` field (we OCR only here). Root is `object`
# because Gemini's JSON mode rejects a bare-array root for some schema
# versions (see MEMORY:feedback_provider_result_dict_typing) — wrapping
# under `lines` keeps ProviderResult.raw_json a dict and keeps us forward-
# compatible with stricter schema validators.
_OCR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "text": {"type": "string"},
                    # OCR confidence is optional — some Gemini variants
                    # return it, others don't. Ignored for now.
                },
                "required": ["bbox", "text"],
            },
        },
    },
    "required": ["lines"],
}

_OCR_SYSTEM = "你是文档 OCR 助手。严格按要求输出 JSON，不要解释。"


def _ocr_prompt() -> str:
    return (
        "提取图片中所有可见文本行，按出现顺序（自上而下、自左而右）输出。"
        "每行两个字段：\n"
        "`bbox`：`[y0,x0,y1,x1]` 归一化到 0–1000（左上角原点，y 向下）；\n"
        "`text`：原文（保留原语言，不要翻译，不要拆分单词）。\n"
        "表格的每个 cell 是独立一行；多行段落每个视觉行是独立一行。"
        "不要返回水印、装饰线条、二维码内容。"
        "不要解释，直接返回 JSON。"
    )


def _pixmap_dims(page_w: float, page_h: float, dpi: int = _RENDER_DPI) -> tuple[int, int]:
    """Mimic `fitz.Page.get_pixmap(dpi=dpi).{width,height}` without rendering.

    PyMuPDF rounds the pixmap dims with `ceil(rect_dim * dpi / 72)` — verified
    against fitz 1.27 at A4 / Letter / non-integer / 1000² page sizes. Letting
    us skip a real rasterise here keeps the lazy text-layer call cheap when
    the render cache hasn't been warmed yet."""
    factor = dpi / 72.0
    return math.ceil(page_w * factor), math.ceil(page_h * factor)


async def _ocr_extract_spans(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
    page_w: float,
    page_h: float,
) -> list[dict[str, Any]]:
    """Call Gemini vision OCR on the rendered page and return spans in
    the same shape `extract_textlayer` would emit from fitz.

    bbox is denormalised from Gemini's `[y0,x0,y1,x1]` 0–1000 back to
    PDF-page units `[x0,y0,x1,y1]` — mirrors translate.py:_denormalise_bbox.
    The image Gemini sees is the 150dpi raster (PDF) or the native raster
    (PNG/JPG), but normalised bbox is image-aspect-ratio-invariant, so the
    `page_w / page_h` we multiply by converts cleanly to whatever unit the
    sidecar reports (PDF points for PDFs, pixels for raster docs).

    Returns [] on any provider error — the caller will write an empty
    sidecar so we don't retry on every open. The frontend degrades to
    no selection on that page, same as the pre-OCR-fallback behaviour.
    """
    # Local imports — avoid pulling provider deps at module-import time
    # (tests that mock `get_provider_for_model` patch the symbol on this
    # module's namespace, so the import has to happen at call time too if
    # we want monkeypatching to work; we expose the lookups via module
    # globals below to make that explicit and tweakable from tests).
    from app.config import get_settings
    from app.provider import get_provider_for_model
    from app.provider.base import ImageBlock, TextBlock
    from app.tools.docs import read_doc_image

    try:
        img = await read_doc_image(workspace, project_id, filename, page=page)
    except (OSError, ValueError):
        return []
    image_block = ImageBlock(data_b64=img["data"], media_type=img["mime"])

    model_id = get_settings().default_translate_model
    try:
        provider = get_provider_for_model(model_id)
    except ValueError:
        return []

    try:
        result = await provider.extract(
            model_id=model_id,
            system_prompt=_OCR_SYSTEM,
            user_content=[TextBlock(text=_ocr_prompt()), image_block],
            response_schema=_OCR_RESPONSE_SCHEMA,
        )
    except Exception:
        # Network failure / quota / 5xx — return empty spans; caller
        # will cache the empty result so we don't slam the provider.
        # The page degrades to "raster only, can't select" same as the
        # pre-OCR-fallback behaviour.
        return []

    raw = result.raw_json
    if not isinstance(raw, dict):
        return []
    lines = raw.get("lines")
    if not isinstance(lines, list):
        return []

    spans: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict):
            continue
        bbox_norm = line.get("bbox")
        text = line.get("text", "")
        if not isinstance(bbox_norm, list) or len(bbox_norm) != 4:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        # Denormalise [y0,x0,y1,x1] 0–1000 → [x0,y0,x1,y1] in page units.
        # Mirrors translate.py:_denormalise_bbox exactly.
        try:
            y0_n, x0_n, y1_n, x1_n = (int(v) for v in bbox_norm)
        except (TypeError, ValueError):
            continue
        x0 = (x0_n / 1000.0) * page_w
        y0 = (y0_n / 1000.0) * page_h
        x1 = (x1_n / 1000.0) * page_w
        y1 = (y1_n / 1000.0) * page_h
        spans.append({
            "bbox": [float(x0), float(y0), float(x1), float(y1)],
            "text": text,
            # font_size is approximate; the frontend overlay scales by
            # bbox HEIGHT (cqh math) so this is mostly informational. We
            # don't get a meaningful per-line font size out of OCR — 12pt
            # is a reasonable middle-ground default.
            "font_size": 12.0,
        })
    return spans


async def extract_textlayer(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
    skip_ocr: bool = False,
) -> dict[str, Any]:
    """Return the text spans for one page of one doc.

    Sidecar lives at `docs/.meta/_textlayer/{filename}/p{page}.json` (see
    `doc_textlayer_dir`). First call extracts via fitz + writes the sidecar;
    if fitz returns nothing usable (image doc or scanned PDF) and
    `skip_ocr=False`, we fall back to a Gemini vision OCR call so the
    overlay still has spans. Subsequent calls deserialise from disk — lazy
    + atomic, same shape as `pdf_render_page`.

    Returns:
        ```
        {
          "filename": str, "page": int,
          "page_w": float, "page_h": float,   # PDF page rect units (points)
                                              # or pixel units for raster docs
          "image_w": int,  "image_h": int,    # raster dims at 150dpi
          "scanned": bool,                    # source page is a raster?
          "text_source": "fitz" | "ocr" | "none",
          "spans": [
            {"bbox": [x0, y0, x1, y1], "text": str, "font_size": float}, …
          ]
        }
        ```

    `scanned` and `text_source` answer different questions: `scanned` is
    about the source page (raster vs vector), `text_source` is about
    where the spans in this sidecar came from (`fitz` for vector spans,
    `ocr` for Gemini-extracted, `none` for "OCR was attempted but
    returned nothing OR OCR was skipped via `skip_ocr=True`"). Downstream
    callers (e.g. translate.py) keep using `scanned` to decide whether
    to run vision-mode translation.

    `skip_ocr=True` bypasses the OCR fallback and emits `spans=[]` with
    `text_source="none"`. Useful for tests and for callers that don't
    want to spend translator-LLM budget on selectable-text overlay.

    Raises:
        FileNotFoundError: sidecar meta for the doc is missing.
        ValueError: page out of range, or the doc lacks a usable extension.
    """
    meta_p = doc_meta_path(workspace, project_id, filename)
    if not meta_p.exists():
        raise FileNotFoundError(f"doc {filename!r} not found")
    meta = json.loads(meta_p.read_text())
    ext = str(meta.get("ext", "")).lower()

    sidecar = doc_textlayer_path(workspace, project_id, filename, page)
    if sidecar.exists():
        return json.loads(sidecar.read_text())

    cache_dir = doc_textlayer_dir(workspace, project_id, filename)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if ext != "pdf":
        # PNG/JPG: single page asset; no fitz text to harvest. We still
        # try OCR (unless skipped) so the overlay has something to hang
        # selection on. `scanned=True` stays — the source IS a raster.
        if page != 1:
            raise ValueError(f"page {page} out of range (1..1)")
        import fitz  # PyMuPDF

        src = doc_path(workspace, project_id, filename)
        pix = fitz.Pixmap(src.read_bytes())
        image_w, image_h = int(pix.width), int(pix.height)
        page_w = float(image_w)
        page_h = float(image_h)

        if skip_ocr:
            ocr_spans: list[dict[str, Any]] = []
        else:
            ocr_spans = await _ocr_extract_spans(
                workspace, project_id, filename,
                page=1, page_w=page_w, page_h=page_h,
            )
        text_source = "ocr" if ocr_spans else "none"

        payload: dict[str, Any] = {
            "filename": filename,
            "page": 1,
            "page_w": page_w,
            "page_h": page_h,
            "image_w": image_w,
            "image_h": image_h,
            "scanned": True,
            "text_source": text_source,
            "spans": ocr_spans,
        }
        atomic_write_text(sidecar, json.dumps(payload, ensure_ascii=False))
        return payload

    import fitz  # PyMuPDF — already a hard dep via `pdf_render_page`.

    src = doc_path(workspace, project_id, filename)
    with fitz.open(src) as pdf:
        if page < 1 or page > pdf.page_count:
            raise ValueError(f"page {page} out of range (1..{pdf.page_count})")
        pg = pdf[page - 1]
        rect = pg.rect
        page_w = float(rect.width)
        page_h = float(rect.height)
        image_w, image_h = _pixmap_dims(page_w, page_h)

        # Aggregate at LINE granularity (one fitz "line" = one visual row of
        # text in the source PDF, already a union over its inner spans).
        # Span-level was too fine: phrases like "Faktur Pajak" are emitted as
        # two spans, which made the cover-mode ghost leak the second word
        # because each fragment was translated independently. Line-level
        # gives the translator the full phrase + the ghost a single bbox to
        # cover. Same downstream shape — frontend code is unchanged.
        spans: list[dict[str, Any]] = []
        data = pg.get_text("dict")
        for block in data.get("blocks", []):
            # type==0 is text blocks; type==1 is image blocks (which on a
            # scanned page is where the page content lives — leave alone).
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_spans = line.get("spans", [])
                if not line_spans:
                    continue
                line_text = "".join(s.get("text", "") for s in line_spans)
                if not line_text.strip():
                    continue
                bbox = line.get("bbox")
                if not bbox:
                    # Defensive: union the spans' bboxes if fitz didn't
                    # surface a line-level one (older PyMuPDF versions).
                    xs = [s.get("bbox", [0,0,0,0]) for s in line_spans]
                    bbox = [
                        min(b[0] for b in xs),
                        min(b[1] for b in xs),
                        max(b[2] for b in xs),
                        max(b[3] for b in xs),
                    ]
                # font_size: pick the dominant span's size (max), so a small
                # superscript doesn't drag the whole line's font-size down.
                font_size = max(
                    (float(s.get("size", 0.0)) for s in line_spans),
                    default=0.0,
                )
                spans.append({
                    "bbox": [float(v) for v in bbox],
                    "text": line_text,
                    "font_size": font_size,
                })

    joined = "".join(s["text"] for s in spans).strip()
    scanned = len(joined) < _SCANNED_TEXT_THRESHOLD

    # Scanned PDF → fitz gave us nothing useful → OCR fallback (unless
    # explicitly suppressed). We deliberately exited the `fitz.open(src)`
    # block first so we're not holding the PDF lock during a multi-second
    # LLM call.
    if scanned and not skip_ocr:
        ocr_spans = await _ocr_extract_spans(
            workspace, project_id, filename,
            page=page, page_w=page_w, page_h=page_h,
        )
        if ocr_spans:
            spans = ocr_spans
            text_source = "ocr"
        else:
            text_source = "none"
    elif scanned:
        text_source = "none"
    else:
        text_source = "fitz"

    payload = {
        "filename": filename,
        "page": page,
        "page_w": page_w,
        "page_h": page_h,
        "image_w": int(image_w),
        "image_h": int(image_h),
        "scanned": scanned,
        "text_source": text_source,
        "spans": spans,
    }
    atomic_write_text(sidecar, json.dumps(payload, ensure_ascii=False))
    return payload
