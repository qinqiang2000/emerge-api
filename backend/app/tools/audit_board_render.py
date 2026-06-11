"""Server-side audit-board composite renderer (B4, 2026-06-11 audit-board plan).

Renders the project's LATEST audit report as annotated page images — one
composite (pages stacked vertically) per audited document. Every rule
evidence quote is resolved to page rects via :func:`locate_quotes` (called
in-process, never over HTTP), then circled on the 150dpi page raster with a
low-alpha fill, a 1-based check-number badge, and a colour keyed to the
check's verdict. This is the universal Cowork fallback: any client that can
show an image can see WHERE the audit evidence sits.

Hard rules honoured here (plan §红线):

- **Coordinates live only inside this render layer.** The rects from
  ``locate_quotes`` die in the PIL draw calls — the returned payload carries
  pixels + rule text (legend), NEVER rect numbers, so nothing coordinate-
  shaped can leak into an agent context or prompt.
- **Derived render only.** Everything composes in memory; nothing is written
  into ``audits/`` (page rasters come from / land in the shared
  ``.cache/_render`` content-addressed cache via ``pdf_render_page``).
- **LLM-free.** locate is pure CPU + warm-sidecar reads; rendering never
  touches a provider. The tool wrapper is read-only and deliberately NOT in
  ``_TOUCHES_PROVIDER``.
- **Doc vision is pulled.** This renders only when explicitly invoked (tool /
  HTTP); no auto-attach path.
"""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

from app.schemas.locate import QuoteLocation
from app.tools.audit_run import read_audit_report
from app.tools.docs import fit_image_for_agent, pdf_render_page
from app.tools.locate import locate_quotes
from app.tools.textlayer import extract_textlayer
from app.workspace.paths import doc_meta_path, doc_path

# Cited pages warmed (fitz+OCR) per render before re-locating misses — bounds
# the OCR cost on a scanned group (see `_locate_with_warm`).
_WARM_CAP = 8

# Verdict → draw colour. Mirrors the board's settled marker palette
# (frontend boardScene.readBoardColors — keep in lockstep): one MAGENTA
# marker for pass AND fail, because annotations must stand out against
# arbitrary document pixels and magenta virtually never occurs in business
# documents (red camouflages on red brand pages, blue reads thin on paper,
# amber collides with highlights — all tried in dogfood 2026-06-11). The
# verdict lives in the legend, not the circle hue. unclear stays amber —
# "couldn't read it" is a different signal than a mark.
_STATUS_COLOR: dict[str, str] = {
    "pass": "#d6219c",
    "fail": "#d6219c",
    "unclear": "#d97706",
}
_DEFAULT_COLOR = "#d97706"  # amber — unknown verdicts render as "unclear"
_INK_COLOR = "#444444"      # corner-badge text — mirrors the ink token family

# `pdf_render_page` rasterises at 150dpi while textlayer rects for PDFs are in
# PDF point units (72/inch) → rect-to-pixel scale is 150/72. Image docs report
# `page_w == image_w` (textlayer contract), so their rects are already pixels.
_PDF_RECT_SCALE = 150.0 / 72.0

# Stacked-pages height cap per doc. Beyond it we keep the FIRST pages and flag
# truncation — a partial board beats a payload that blows the agent budget
# (`fit_image_for_agent` then squeezes the long edge to 1568px anyway).
_MAX_BOARD_HEIGHT_PX = 4000
_PAGE_GAP_PX = 12

# Low-alpha fill + outline (spike trap: a bare 2px stroke is invisible/unhittable
# once the page is zoomed out; the fill is what makes a hit readable).
_FILL_ALPHA = 50
_OUTLINE_W = 3
_RECT_PAD = 4
_BADGE_R = 16


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _font(size: int):
    """Pillow's bundled bitmap font, scaled when the runtime supports it
    (Pillow >= 10.1 accepts ``size=``); the unscaled fallback keeps old
    runtimes rendering instead of crashing."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - pillow < 10.1
        return ImageFont.load_default()


def _resolve_doc(ev_doc: str, filenames: list[str]) -> Optional[str]:
    """Map an evidence ``doc`` citation onto a group filename.

    Exact filename first; else a UNIQUE substring hit ("报价单" → "报价单.jpg"
    — same leniency as `L1FieldRef.doc`, which is where L1-synthesized
    evidence docs come from). 0 or many hits → None (the citation simply
    isn't drawn; never an error)."""
    if ev_doc in filenames:
        return ev_doc
    if not ev_doc:
        return None
    hits = [fn for fn in filenames if ev_doc in fn]
    return hits[0] if len(hits) == 1 else None


def _page_count(workspace: Path, slug: str, filename: str) -> int:
    try:
        meta = json.loads(doc_meta_path(workspace, slug, filename).read_text())
        return max(1, int(meta.get("page_count", 1) or 1))
    except (OSError, json.JSONDecodeError, ValueError):
        return 1


async def _load_pages(
    workspace: Path, slug: str, filename: str,
) -> list[tuple[Image.Image, float]]:
    """Page rasters for one doc as ``(PIL image, rect→pixel scale)`` tuples.

    PNG/JPG → the doc bytes themselves (single page, rects already pixels).
    PDF → `pdf_render_page` per page (respects its content-addressed cache).
    A page that fails to load stops the walk; an unreadable doc yields []
    (caller skips it — mirrors run_audit's skip-unrenderable discipline)."""
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    if ext in ("png", "jpg", "jpeg"):
        try:
            with Image.open(doc_path(workspace, slug, filename)) as im:
                return [(im.convert("RGB"), 1.0)]
        except Exception:
            return []
    if ext != "pdf":
        return []
    pages: list[tuple[Image.Image, float]] = []
    for page in range(1, _page_count(workspace, slug, filename) + 1):
        try:
            rendered = await pdf_render_page(workspace, slug, filename, page=page)
            with Image.open(rendered) as im:
                pages.append((im.convert("RGB"), _PDF_RECT_SCALE))
        except Exception:
            break  # past the last renderable page
    return pages


def _draw_badge(
    draw: "ImageDraw.ImageDraw",
    x: float,
    y: float,
    n: int,
    color: tuple[int, int, int],
    canvas_size: tuple[int, int],
) -> None:
    """Solid circle with the white 1-based check number, anchored at (x, y)
    (an evidence rect's top-left corner), clamped inside the canvas."""
    w, h = canvas_size
    cx = min(max(x, _BADGE_R), w - _BADGE_R)
    cy = min(max(y, _BADGE_R), h - _BADGE_R)
    draw.ellipse(
        (cx - _BADGE_R, cy - _BADGE_R, cx + _BADGE_R, cy + _BADGE_R),
        fill=color + (255,),
    )
    font = _font(int(_BADGE_R * 1.2))
    text = str(n)
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    draw.text((cx - tw / 2 - tb[0], cy - th / 2 - tb[1]), text,
              fill=(255, 255, 255, 255), font=font)


def _draw_corner_badge(
    draw: "ImageDraw.ImageDraw", canvas_w: int, numbers: list[int],
) -> None:
    """Top-right corner note listing check numbers whose evidence cites this
    doc but could not be located (status none / page outside the composite)."""
    text = "unlocated: " + ", ".join(str(n) for n in numbers)
    font = _font(22)
    tb = draw.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    pad = 8
    x1 = canvas_w - 12
    x0 = max(0, x1 - tw - 2 * pad)
    y0 = 12
    y1 = y0 + th + 2 * pad
    draw.rounded_rectangle(
        (x0, y0, x1, y1), radius=6,
        fill=(255, 255, 255, 220), outline=_rgb(_INK_COLOR) + (255,), width=2,
    )
    draw.text((x0 + pad - tb[0], y0 + pad - tb[1]), text,
              fill=_rgb(_INK_COLOR) + (255,), font=font)


def _compose_doc_image(
    pages: list[tuple[Image.Image, float]],
    items: list[dict[str, Any]],
    locs: list[QuoteLocation],
) -> Optional[tuple[bytes, bool]]:
    """Stack a doc's pages vertically and paint the evidence annotations.

    ``items`` are ``{n, status, page, quote}`` evidence entries (1-based check
    number + that check's verdict) aligned index-for-index with ``locs``.
    Returns ``(png_bytes, truncated)`` or None when no page rendered."""
    if not pages:
        return None

    kept: list[tuple[Image.Image, float]] = []
    total_h = 0
    for img, scale in pages:
        add = (_PAGE_GAP_PX if kept else 0) + img.height
        if kept and total_h + add > _MAX_BOARD_HEIGHT_PX:
            break  # cap: keep first pages, flag truncation below
        total_h += add
        kept.append((img, scale))
    truncated = len(kept) < len(pages)

    width = max(img.width for img, _ in kept)
    canvas = Image.new("RGB", (width, total_h), "white")
    offsets: dict[int, tuple[int, float]] = {}  # 1-based page → (y offset, scale)
    y = 0
    for page_no, (img, scale) in enumerate(kept, start=1):
        canvas.paste(img, (0, y))
        offsets[page_no] = (y, scale)
        y += img.height + _PAGE_GAP_PX

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    unlocated: list[int] = []
    for item, loc in zip(items, locs):
        # status none, no rects, or located on a page the cap dropped → the
        # corner badge takes over (never a hard failure).
        if loc.status == "none" or not loc.rects or loc.page not in offsets:
            unlocated.append(item["n"])
            continue
        y_off, scale = offsets[loc.page]
        color = _rgb(_STATUS_COLOR.get(item["status"], _DEFAULT_COLOR))
        badge_at: Optional[tuple[float, float]] = None
        for rect in loc.rects:
            if len(rect) < 4:
                continue
            x0, y0_, x1, y1_ = (float(v) * scale for v in rect[:4])
            box = (
                max(0.0, x0 - _RECT_PAD),
                max(0.0, y_off + y0_ - _RECT_PAD),
                min(float(width), x1 + _RECT_PAD),
                min(float(canvas.height), y_off + y1_ + _RECT_PAD),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue  # degenerate rect — nothing to paint
            # Low-alpha fill + outline: visible AND clickable-sized at any zoom.
            draw.rounded_rectangle(
                box, radius=6,
                fill=color + (_FILL_ALPHA,),
                outline=color + (255,), width=_OUTLINE_W,
            )
            if badge_at is None:
                badge_at = (box[0], box[1])
        if badge_at is not None:
            _draw_badge(draw, badge_at[0], badge_at[1], item["n"], color, canvas.size)
        else:
            unlocated.append(item["n"])

    if unlocated:
        _draw_corner_badge(draw, width, sorted(set(unlocated)))

    out = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), truncated


async def _locate_with_warm(
    workspace: Path, slug: str, fn: str, items: list[dict[str, Any]]
) -> list[QuoteLocation]:
    """Locate every item's quote, self-healing cold scanned pages.

    `locate_quotes` reads WARM text-layer sidecars only (LLM-free render path,
    `skip_ocr`) — a quote on a scanned page whose OCR sidecar is cold can never
    hit. The frontend board warms via GET /textlayer; this tool has no
    frontend, so it warms server-side itself (fitz+OCR via `extract_textlayer`,
    capped) for the pages of MISSED evidence, then re-locates. Without it a
    scanned anchor (报价单.pdf) circles nothing over MCP (dogfood 2026-06-11)."""
    quotes = [{"page": it["page"], "quote": it["quote"]} for it in items]
    locs = await locate_quotes(workspace, slug, fn, quotes=quotes)
    miss = [
        i for i, lc in enumerate(locs)
        if lc.status == "none" or not lc.rects
    ]
    if not miss:
        return locs
    warm_pages: list[int] = []
    for i in miss:
        p = items[i].get("page")
        page = int(p) if isinstance(p, int) and p > 0 else 1
        if page not in warm_pages:
            warm_pages.append(page)
    for page in warm_pages[:_WARM_CAP]:
        try:
            await extract_textlayer(workspace, slug, fn, page=page)
        except Exception:
            pass  # best-effort warm — a failed OCR just leaves that page cold
    relocated = await locate_quotes(workspace, slug, fn, quotes=quotes)
    # keep the better of the two passes per item (warm pass should dominate,
    # but never regress an item the cold pass had already located)
    return [
        relocated[i] if (relocated[i].status != "none" and relocated[i].rects)
        else locs[i]
        for i in range(len(locs))
    ]


async def render_audit_board(workspace: Path, slug: str) -> dict[str, Any]:
    """Compose the latest audit report into annotated per-doc images.

    Returns::

        {
          "legend":   [{"n": int, "rule": str, "status": "pass|fail|unclear"}],
          "images":   [{"doc": str, "media_type": str, "data_b64": str}],
          "truncated": bool,   # some doc had pages dropped by the height cap
        }

    One image per readable doc in the report group; each image is squeezed
    through `fit_image_for_agent` (SDK budget — may re-encode to JPEG).
    Raises ``AuditError("audit_no_report")`` when the project has never been
    audited (propagated from `read_audit_report`)."""
    report = await read_audit_report(workspace, slug)

    checks: list[dict[str, Any]] = [
        c for c in (report.get("checks") or []) if isinstance(c, dict)
    ]
    legend = [
        {
            "n": i + 1,
            "rule": str(c.get("rule") or ""),
            "status": str(c.get("status") or "unclear"),
        }
        for i, c in enumerate(checks)
    ]

    # group is {filename: filename} (run_audit contract); keep insertion order.
    filenames: list[str] = []
    for fn in (report.get("group") or {}).values():
        if isinstance(fn, str) and fn not in filenames:
            filenames.append(fn)

    # Evidence per doc, in check order: {n, status, page, quote}.
    per_doc: dict[str, list[dict[str, Any]]] = {fn: [] for fn in filenames}
    for i, check in enumerate(checks):
        status = str(check.get("status") or "unclear")
        for ev in check.get("evidence") or []:
            if not isinstance(ev, dict):
                continue
            fn = _resolve_doc(str(ev.get("doc") or ""), filenames)
            if fn is None:
                continue
            per_doc[fn].append({
                "n": i + 1,
                "status": status,
                "page": ev.get("page"),
                "quote": str(ev.get("quote") or ""),
            })

    images: list[dict[str, str]] = []
    truncated = False
    for fn in filenames:
        items = per_doc[fn]
        # In-process locate (red line: rects never travel over HTTP / into any
        # tool result — they are consumed by the PIL draw below and discarded).
        locs = await _locate_with_warm(workspace, slug, fn, items) if items else []
        pages = await _load_pages(workspace, slug, fn)
        composed = _compose_doc_image(pages, items, locs)
        if composed is None:
            continue  # unrenderable doc — same skip as run_audit
        png_bytes, doc_truncated = composed
        truncated = truncated or doc_truncated
        fitted, mime = fit_image_for_agent(png_bytes, "image/png")
        images.append({
            "doc": fn,
            "media_type": mime,
            "data_b64": base64.standard_b64encode(fitted).decode("ascii"),
        })

    return {"legend": legend, "images": images, "truncated": truncated}
