"""PDF text-layer extraction (review-mode UX only).

Drives the transparent text overlay that lets users select + copy the
original text on top of the rasterised PDF page that `pdf_render_page`
produces. The extraction reads fitz's vector text via `get_text("dict")`
and persists a per-page sidecar so subsequent calls hit disk, mirroring the
lazy + atomic pattern of `pdf_render_page`.

Hard rules this respects:
- bbox / coordinates are NEVER fed back into the extract or runtime prompt
  path. The sidecar is consumed by the frontend review overlay only.
- No image few-shot; this module touches neither extract nor labeler.
- Scanned-PDF / image-doc pages produce an empty `spans=[]` sidecar with
  `scanned=true` so the frontend can honestly degrade (no overlay, user
  perceives "cannot select" → knows the page is scanned).
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


def _pixmap_dims(page_w: float, page_h: float, dpi: int = _RENDER_DPI) -> tuple[int, int]:
    """Mimic `fitz.Page.get_pixmap(dpi=dpi).{width,height}` without rendering.

    PyMuPDF rounds the pixmap dims with `ceil(rect_dim * dpi / 72)` — verified
    against fitz 1.27 at A4 / Letter / non-integer / 1000² page sizes. Letting
    us skip a real rasterise here keeps the lazy text-layer call cheap when
    the render cache hasn't been warmed yet."""
    factor = dpi / 72.0
    return math.ceil(page_w * factor), math.ceil(page_h * factor)


async def extract_textlayer(
    workspace: Path,
    project_id: str,
    filename: str,
    *,
    page: int,
) -> dict[str, Any]:
    """Return the text spans for one page of one doc.

    Sidecar lives at `docs/.meta/_textlayer/{filename}/p{page}.json` (see
    `doc_textlayer_dir`). First call extracts via fitz + writes the sidecar;
    subsequent calls deserialise from disk — lazy + atomic, same shape as
    `pdf_render_page`.

    Returns:
        ```
        {
          "filename": str, "page": int,
          "page_w": float, "page_h": float,   # PDF page rect units (points)
          "image_w": int,  "image_h": int,    # raster dims at 150dpi
          "scanned": bool,
          "spans": [
            {"bbox": [x0, y0, x1, y1], "text": str, "font_size": float}, …
          ]
        }
        ```

    For non-PDF docs (PNG/JPG single-page assets) `spans=[]`, `scanned=true`,
    and `page_w/page_h` collapse onto `image_w/image_h` (image pixels) — the
    overlay path is a no-op for raster docs.

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
        # PNG/JPG: single page asset; treat as a scanned raster (no text
        # layer to harvest). `fitz.Pixmap(bytes)` reports native pixel dims
        # (unlike `fitz.open(stream=…, filetype=…)`, which projects raster
        # files into 72dpi point space and would give us scaled-down dims).
        if page != 1:
            raise ValueError(f"page {page} out of range (1..1)")
        import fitz  # PyMuPDF

        src = doc_path(workspace, project_id, filename)
        pix = fitz.Pixmap(src.read_bytes())
        image_w, image_h = int(pix.width), int(pix.height)
        payload: dict[str, Any] = {
            "filename": filename,
            "page": 1,
            "page_w": float(image_w),
            "page_h": float(image_h),
            "image_w": int(image_w),
            "image_h": int(image_h),
            "scanned": True,
            "spans": [],
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

    payload = {
        "filename": filename,
        "page": page,
        "page_w": page_w,
        "page_h": page_h,
        "image_w": int(image_w),
        "image_h": int(image_h),
        "scanned": scanned,
        "spans": spans,
    }
    atomic_write_text(sidecar, json.dumps(payload, ensure_ascii=False))
    return payload
