// board_geometry.js — the single source of truth for audit-board geometry.
//
// Three consumers, three ingestion paths (plan
// docs/superpowers/plans/2026-06-12-board-geometry-and-doodle-signal.md, §G —
// born after the SAME formula was hand-ported three times and v9 commit
// 707e3b4 had to chase a missed ray∩ellipse trim in the third copy):
//
//   1. web excalidraw board — frontend/src/components/Board/boardScene.ts
//      side-effect-imports this file through the vite alias `@board-geometry`
//      and reads `globalThis.BoardGeom`. The excalidraw dialect (skeleton
//      assembly, id contract, colors) stays in boardScene; only geometry
//      lives here. Types: frontend/src/components/Board/board-geometry.d.ts
//      (hand-maintained, keep in lockstep).
//   2. MCP Apps iframe board — backend/app/skills/board_app.html gets this
//      file injected VERBATIM into an inline <script> at serve time
//      (mcp_server.py::_board_app_html replaces /*__BOARD_GEOMETRY_JS__*/).
//      That is why this must stay a CLASSIC script: no import/export, plain
//      top-level declarations, exports only via the globalThis.BoardGeom bag
//      at the bottom.
//   3. Pillow composite — backend/app/tools/board_geom.py regex-extracts the
//      text between the GEOM-JSON markers below and json.loads it (zero JS
//      runtime). That is why the GEOM literal must stay STRICT JSON:
//      double-quoted keys, no comments inside, no trailing comma.
"use strict";

// All shared constants in one strict-JSON literal (see consumer #3 above).
// SCALE/COL_GAP/ROW_GAP/ELLIPSE_PAD/ARROW_GAP/STROKE_* are board units;
// DASH_ON:DASH_OFF is the dash rhythm (SVG stroke-dasharray and the Pillow
// renderer derive from the same ratio); RENDER_DPI mirrors
// backend/app/tools/textlayer.py::_RENDER_DPI (the page-raster dpi).
const GEOM = /*GEOM-JSON-BEGIN*/ {"SCALE": 0.55, "COL_GAP": 120, "ROW_GAP": 24, "PAGES_PER_COL": 4, "ELLIPSE_PAD": 8, "ARROW_GAP": 8, "STROKE_W": 3.5, "STROKE_ARROW": 3, "DASH_ON": 10, "DASH_OFF": 7, "RENDER_DPI": 150} /*GEOM-JSON-END*/;

// ── Unit conversion ─────────────────────────────────────────────────────────
//
// locate-quotes rects are PDF points; the page raster the board displays is
// rendered at RENDER_DPI (`textlayer.py::_pixmap_dims` computes pixmap dims
// as ceil(point_dim * dpi / 72.0), kept in lockstep with `pdf_render_page`).
// So for PDFs: raster pixel = point × RENDER_DPI/72. Raster docs (jpg/png)
// have no point space — textlayer.py's non-PDF branch sets
// `page_w = float(image_w)` (pixel units), so quote rects already arrive in
// raster pixels and the factor is 1.
function pxPerPtFor(ext) {
  return String(ext).toLowerCase().replace(/^\./, "") === "pdf" ? GEOM.RENDER_DPI / 72 : 1;
}

// Key for the laid-pages map: one entry per (doc, 1-based page).
function pageKey(doc, page) {
  return doc + "#p" + page;
}

// ── Column layout ───────────────────────────────────────────────────────────
//
// One column band per doc, pages stacked top-to-bottom and wrapping into
// sub-columns of PAGES_PER_COL (ROW_GAP apart) — keeps a many-paged doc from
// stretching the board into a strip (an 18-page doc degraded fit-to-viewport
// to ~10% zoom, prod dogfood 2026-06-11). The doc-to-doc COL_GAP stays wider
// so docs still read as groups.
//
// `docs`: [{name, ext, pages: [{page, w, h}, ...]}, ...] — w/h are measured
// raster dims (web passes real <img> dims; the iframe board passes A4
// placeholders and re-lays on img onload). Returns Map<pageKey, laid page>
// where each laid page is {doc, page, x, y, w, h, k}; multiply a locate-rect
// coordinate (PDF points for pdf, raster px for jpg/png) by `k` to get board
// units: k = pxPerPtFor(ext) × scale.
function layoutPages(docs, scale) {
  if (scale == null) scale = GEOM.SCALE;
  const out = new Map();
  let x = 0;
  for (const doc of docs) {
    const k = pxPerPtFor(doc.ext) * scale;
    let y = 0;
    let colW = 0;
    let colX = x;
    let docRight = x;
    let inCol = 0;
    for (const p of doc.pages) {
      const w = p.w * scale;
      const h = p.h * scale;
      if (inCol >= GEOM.PAGES_PER_COL) {
        colX += colW + GEOM.ROW_GAP;
        y = 0;
        colW = 0;
        inCol = 0;
      }
      out.set(pageKey(doc.name, p.page), { doc: doc.name, page: p.page, x: colX, y, w, h, k });
      y += h + GEOM.ROW_GAP;
      colW = Math.max(colW, w);
      docRight = Math.max(docRight, colX + colW);
      inCol++;
    }
    if (doc.pages.length > 0) x = docRight + GEOM.COL_GAP;
  }
  return out;
}

// ── Evidence mapping ────────────────────────────────────────────────────────

// Union a list of raw [x0, y0, x1, y1] rects (same units in = same units
// out); entries shorter than 4 are malformed locate output and are skipped.
// Returns {x, y, w, h} or null when nothing usable remains.
function unionRect(rects) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  let any = false;
  for (const r of rects) {
    if (!Array.isArray(r) || r.length < 4) continue;
    any = true;
    x0 = Math.min(x0, r[0]);
    y0 = Math.min(y0, r[1]);
    x1 = Math.max(x1, r[2]);
    y1 = Math.max(y1, r[3]);
  }
  return any ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
}

// Board-space ellipse of one located evidence: union the (possibly
// multi-line) source-unit rects, convert source units → board units via the
// page's `k`, offset by the page position, pad by ELLIPSE_PAD so the ellipse
// doesn't hug the glyphs. Returns both consumption shapes at once —
// {x, y, w, h} for excalidraw skeletons, {cx, cy, rx, ry} for SVG/arrow math
// — or null when the rect list is empty/malformed.
function evidenceEllipse(rects, page) {
  const u = unionRect(rects);
  if (!u) return null;
  const x = page.x + u.x * page.k - GEOM.ELLIPSE_PAD;
  const y = page.y + u.y * page.k - GEOM.ELLIPSE_PAD;
  const w = u.w * page.k + GEOM.ELLIPSE_PAD * 2;
  const h = u.h * page.k + GEOM.ELLIPSE_PAD * 2;
  return { x, y, w, h, cx: x + w / 2, cy: y + h / 2, rx: w / 2, ry: h / 2 };
}

// Trim the center-to-center segment of two ellipses to run ELLIPSE EDGE to
// ellipse edge (+gap). A center-to-center shaft ran straight through the
// circled text and parked the arrowhead ON it (dogfood 2026-06-11), and the
// excalidraw skeleton start/end bindings don't retrim programmatic scenes —
// so the geometry is computed here, by hand, for every consumer.
// a/b: {cx, cy, rx, ry}. Returns {sx, sy, ex, ey} or null for coincident
// centers (norm 0 — no direction to trim along).
function rayEllipseTrim(a, b, gap) {
  if (gap == null) gap = GEOM.ARROW_GAP;
  const dx = b.cx - a.cx;
  const dy = b.cy - a.cy;
  const norm = Math.hypot(dx, dy);
  if (!norm) return null;
  // ray ∩ ellipse: t = 1/√((dx/rx)² + (dy/ry)²) along (dx,dy) from center
  const tA = 1 / Math.hypot(dx / Math.max(a.rx, 1), dy / Math.max(a.ry, 1));
  const tB = 1 / Math.hypot(dx / Math.max(b.rx, 1), dy / Math.max(b.ry, 1));
  return {
    sx: a.cx + dx * tA + (dx / norm) * gap,
    sy: a.cy + dy * tA + (dy / norm) * gap,
    ex: b.cx - dx * tB - (dx / norm) * gap,
    ey: b.cy - dy * tB - (dy / norm) * gap,
  };
}

// Greedy stride-2 cross-doc pairing of one check's evidence centers (any
// objects carrying a `doc` key, in citation order). The judge cites paired
// quotes adjacently (报价单行, 对应物料页, 下一行, …), so a many-match check
// fans out one pair per adjacent cross-doc couple; stride-2 keeps an
// alternating A,B,A,B sequence from double-connecting (B of pair 1 with A of
// pair 2). A 2-evidence check degenerates to the single pair it always had.
function crossDocPairs(centers) {
  const pairs = [];
  let i = 0;
  while (i + 1 < centers.length) {
    if (centers[i].doc !== centers[i + 1].doc) {
      pairs.push([centers[i], centers[i + 1]]);
      i += 2;
    } else {
      i += 1;
    }
  }
  return pairs;
}

// ── Reverse mapping (board → document) ──────────────────────────────────────

// Anchor a board-space bounds (e.g. a user doodle) back onto a document page:
// take the bounds center, find the laid page whose frame contains it
// (boundaries inclusive), and convert the bounds to SOURCE units —
// (coord − page.x|y) / page.k — clamped into the page frame. Returns
// {doc, page, rect: [x0, y0, x1, y1]} (rect in PDF points for pdf docs,
// raster px for jpg/png), or null when the center lands on no page (doodle
// in empty board space). Powers the doodle→teaching-signal loop (plan §D):
// the rect itself stays in the render layer, only derived TEXT ever leaves.
function anchorForBounds(bounds, laidPages) {
  const cx = bounds.x + bounds.w / 2;
  const cy = bounds.y + bounds.h / 2;
  for (const p of laidPages.values()) {
    if (cx < p.x || cx > p.x + p.w || cy < p.y || cy > p.y + p.h) continue;
    const srcW = p.w / p.k;
    const srcH = p.h / p.k;
    const cl = (v, hi) => Math.min(Math.max(v, 0), hi);
    return {
      doc: p.doc,
      page: p.page,
      rect: [
        cl((bounds.x - p.x) / p.k, srcW),
        cl((bounds.y - p.y) / p.k, srcH),
        cl((bounds.x + bounds.w - p.x) / p.k, srcW),
        cl((bounds.y + bounds.h - p.y) / p.k, srcH),
      ],
    };
  }
  return null;
}

globalThis.BoardGeom = {
  GEOM,
  pxPerPtFor,
  layoutPages,
  unionRect,
  evidenceEllipse,
  rayEllipseTrim,
  crossDocPairs,
  anchorForBounds,
  pageKey,
};
