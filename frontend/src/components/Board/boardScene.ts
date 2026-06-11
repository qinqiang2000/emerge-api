// boardScene — pure scene-building math for the audit board.
//
// Everything here is a plain function over plain data: no excalidraw import,
// no fetch, no DOM beyond `readBoardColors` (getComputedStyle, with hex
// fallbacks so it stays test/jsdom-safe). BoardOverlay feeds measured page
// dimensions + locate-quotes results in, gets element skeletons out, and runs
// them through `convertToExcalidrawElements(skeletons, {regenerateIds:false})`
// — the id contract below is what the rail↔canvas linkage keys on, so ids are
// deterministic and must never be regenerated (spike trap #1).
//
// Id namespaces (everything else on the canvas is a user-drawn note):
//   img-{doc}-p{n}    locked page raster
//   lbl-{doc}-p{n}    locked page caption
//   ev-{checkIdx}-{evIdx}   evidence highlight ellipse
//   arrow-{checkIdx}        cross-doc evidence arrow
//   badge-{doc}             "unlocated evidence" corner badge
//   ring-focus              the (single) focus ring

/** One excalidraw element skeleton — kept structurally untyped so this module
 *  never imports from `@excalidraw/excalidraw` (the pure layer must not pull
 *  the 1.5MB canvas dep into test or main bundles). */
export type Skeleton = Record<string, unknown>

// ── Layout constants (ported from the spike) ───────────────────────────────

export const LAYOUT_SCALE = 0.55
export const COL_GAP = 120
export const ROW_GAP = 24

/** Padding (board units) around an evidence rect so the ellipse doesn't hug
 *  the glyphs. Same value the spike used. */
export const ELLIPSE_PAD = 8

// ── Unit conversion ─────────────────────────────────────────────────────────
//
// locate-quotes rects are PDF points; the page raster the board displays is
// rendered at 150dpi (`backend/app/tools/textlayer.py::_RENDER_DPI = 150`,
// `_pixmap_dims` computes pixmap dims as ceil(point_dim * dpi / 72.0), kept in
// lockstep with `pdf_render_page`). So for PDFs: raster pixel = point × 150/72.
export const PX_PER_PT = 150 / 72

/** Raster docs (jpg/png) have no point space — textlayer.py's non-PDF branch
 *  sets `page_w = float(image_w)` (pixel units), so quote rects already arrive
 *  in raster pixels and the factor is 1. */
export function pxPerPtFor(ext: string): number {
  return ext.toLowerCase().replace(/^\./, '') === 'pdf' ? PX_PER_PT : 1
}

// ── Deterministic ids ───────────────────────────────────────────────────────

export const imgId = (doc: string, page: number) => `img-${doc}-p${page}`
export const lblId = (doc: string, page: number) => `lbl-${doc}-p${page}`
export const evId = (checkIdx: number, evIdx: number) => `ev-${checkIdx}-${evIdx}`
export const arrowId = (checkIdx: number) => `arrow-${checkIdx}`
export const badgeId = (doc: string) => `badge-${doc}`
export const RING_ID = 'ring-focus'

/** Everything the board itself draws. Canvas elements whose id does NOT match
 *  (and that aren't text bound into one of ours, e.g. an arrow label) are
 *  user-drawn notes — they get persisted to board_notes. */
export const OWN_ID_RE = /^(img-|lbl-|ev-|arrow-|badge-|ring-focus$)/

/** Parse the check index back out of an `ev-*` / `arrow-*` element id.
 *  Returns null for any other id (user notes, images, ring). */
export function checkIdxOfElementId(id: string): number | null {
  const m = id.match(/^(?:ev|arrow)-(\d+)(?:-\d+)?$/)
  return m ? Number(m[1]) : null
}

// ── Colors (semantic tokens → canvas hex) ───────────────────────────────────

export interface BoardColors {
  /** token --moss */ pass: string
  /** token --rose */ fail: string
  /** token --ochre */ unclear: string
  /** token --ink-3 */ chrome: string
  /** token --paper-2 */ canvas: string
}

function cssVar(name: string, fallback: string): string {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch {
    return fallback
  }
}

/** Excalidraw paints raw hex, not CSS vars — resolve the semantic tokens at
 *  runtime so a theme change flows into the canvas. Fallbacks (spike palette)
 *  only fire outside a themed DOM (tests, SSR-ish edge). */
export function readBoardColors(): BoardColors {
  return {
    pass: cssVar('--moss', '#7c8c4d'),
    fail: cssVar('--rose', '#b54a48'),
    unclear: cssVar('--ochre', '#b8860b'),
    chrome: cssVar('--ink-3', '#6b6258'),
    canvas: cssVar('--paper-2', '#faf8f4'),
  }
}

export type CheckStatus = 'pass' | 'fail' | 'unclear'

export function statusColor(status: CheckStatus, colors: BoardColors): string {
  return status === 'pass' ? colors.pass : status === 'fail' ? colors.fail : colors.unclear
}

const STATUS_MARK: Record<CheckStatus, string> = { pass: '✓', fail: '✗', unclear: '?' }

// ── Column layout ───────────────────────────────────────────────────────────

export interface BoardDocInput {
  /** doc filename (group key) */
  name: string
  /** file extension — picks the point→pixel factor (pdf vs raster) */
  ext: string
  /** measured raster dims per page, 1-based page numbers, in source order */
  pages: { page: number; w: number; h: number }[]
}

export interface LaidPage {
  doc: string
  page: number
  /** board-space position/size (raster px × scale) */
  x: number
  y: number
  w: number
  h: number
  /** multiply a locate rect coordinate (PDF points for pdf, raster px for
   *  jpg/png) by `k` to get board units: k = pxPerPt(ext) × scale */
  k: number
}

export const pageKey = (doc: string, page: number) => `${doc}#p${page}`

/** One column per doc, pages stacked top-to-bottom — the spike's layout math
 *  verbatim: x advances by the column's widest page + COL_GAP, y by page
 *  height + ROW_GAP. */
export function layoutPages(
  docs: BoardDocInput[],
  scale: number = LAYOUT_SCALE,
): Map<string, LaidPage> {
  const out = new Map<string, LaidPage>()
  let x = 0
  for (const doc of docs) {
    const k = pxPerPtFor(doc.ext) * scale
    let y = 0
    let colW = 0
    for (const p of doc.pages) {
      const w = p.w * scale
      const h = p.h * scale
      out.set(pageKey(doc.name, p.page), { doc: doc.name, page: p.page, x, y, w, h, k })
      y += h + ROW_GAP
      colW = Math.max(colW, w)
    }
    if (doc.pages.length > 0) x += colW + COL_GAP
  }
  return out
}

// ── Page skeletons ──────────────────────────────────────────────────────────

/** Locked image element + caption per laid-out page. `fileId` equals the
 *  element id so the overlay registers the dataURL under the same key via
 *  `api.addFiles`. */
export function buildPageSkeletons(pages: LaidPage[], colors: BoardColors): Skeleton[] {
  const skeletons: Skeleton[] = []
  for (const p of pages) {
    skeletons.push({
      type: 'image',
      id: imgId(p.doc, p.page),
      fileId: imgId(p.doc, p.page),
      x: p.x,
      y: p.y,
      width: p.w,
      height: p.h,
      locked: true,
    })
    skeletons.push({
      type: 'text',
      id: lblId(p.doc, p.page),
      x: p.x,
      y: p.y - 40,
      text: `${p.doc} · p${p.page}`,
      fontSize: 20,
      strokeColor: colors.chrome, // token --ink-3
      locked: true,
    })
  }
  return skeletons
}

// ── Evidence overlays ───────────────────────────────────────────────────────

/** One evidence row joined with its locate-quotes result. `rects` are in the
 *  doc's source units (PDF points / raster px); `status:'none'` or an empty
 *  rect list means "unlocated" → corner badge instead of an ellipse. */
export interface EvidenceOnBoard {
  checkIdx: number
  evIdx: number
  doc: string
  page: number | null
  rects: number[][]
  status: string
}

export interface Bounds { x: number; y: number; w: number; h: number }

export function unionBounds(boxes: Bounds[]): Bounds | null {
  if (!boxes.length) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const b of boxes) {
    x0 = Math.min(x0, b.x)
    y0 = Math.min(y0, b.y)
    x1 = Math.max(x1, b.x + b.w)
    y1 = Math.max(y1, b.y + b.h)
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

/** Board-space bounds of one located evidence: union the (possibly multi-line)
 *  rects, convert source units → board units via the page's `k`, offset by the
 *  page position, pad. Same `(imgX + x0·k)` mapping as the spike / BBoxRect. */
export function evidenceBounds(rects: number[][], page: LaidPage): Bounds | null {
  const boxes: Bounds[] = []
  for (const r of rects) {
    if (!Array.isArray(r) || r.length < 4) continue
    const [x0, y0, x1, y1] = r
    boxes.push({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 })
  }
  const u = unionBounds(boxes)
  if (!u) return null
  return {
    x: page.x + u.x * page.k - ELLIPSE_PAD,
    y: page.y + u.y * page.k - ELLIPSE_PAD,
    w: u.w * page.k + ELLIPSE_PAD * 2,
    h: u.h * page.k + ELLIPSE_PAD * 2,
  }
}

/** Build the per-check overlays:
 *    located evidence → low-alpha-filled ellipse (`fillStyle:'solid',
 *      opacity:40` — spike trap #4: a 2px outline alone is neither visible
 *      nor clickable once zoomed out);
 *    a check whose located evidence spans ≥2 docs → dashed arrow between the
 *      first two docs' ellipses, labelled ✓/✗ (? for unclear);
 *    unlocated evidence → per-doc corner badge listing the 1-based check
 *      numbers (never a hard failure — the quote still reads in the rail). */
export function buildCheckOverlays(
  checks: { status: CheckStatus }[],
  evidences: EvidenceOnBoard[],
  pages: Map<string, LaidPage>,
  colors: BoardColors,
): Skeleton[] {
  const skeletons: Skeleton[] = []
  const unlocatedByDoc = new Map<string, Set<number>>()
  // per check: located ellipse centers in board space, with their doc
  const centersByCheck = new Map<number, { doc: string; cx: number; cy: number; id: string }[]>()

  for (const ev of evidences) {
    const check = checks[ev.checkIdx]
    if (!check) continue
    const page = ev.page != null ? pages.get(pageKey(ev.doc, ev.page)) : undefined
    const located = ev.status !== 'none' && ev.rects.length > 0 && page != null
    if (!located || !page) {
      // unlocated → badge on the doc's column (if the doc is on the board)
      if ([...pages.keys()].some((k) => k.startsWith(`${ev.doc}#p`))) {
        let set = unlocatedByDoc.get(ev.doc)
        if (!set) { set = new Set(); unlocatedByDoc.set(ev.doc, set) }
        set.add(ev.checkIdx)
      }
      continue
    }
    const b = evidenceBounds(ev.rects, page)
    if (!b) continue
    const color = statusColor(check.status, colors)
    const id = evId(ev.checkIdx, ev.evIdx)
    skeletons.push({
      type: 'ellipse',
      id,
      x: b.x,
      y: b.y,
      width: b.w,
      height: b.h,
      strokeColor: color,
      strokeWidth: 2,
      // trap #4 — low-alpha fill: visible highlight zone + clickable interior
      backgroundColor: color,
      fillStyle: 'solid',
      opacity: 40,
    })
    let centers = centersByCheck.get(ev.checkIdx)
    if (!centers) { centers = []; centersByCheck.set(ev.checkIdx, centers) }
    centers.push({ doc: ev.doc, cx: b.x + b.w / 2, cy: b.y + b.h / 2, id })
  }

  // cross-doc arrows — only when a check's located evidence spans ≥2 docs
  for (const [checkIdx, centers] of centersByCheck) {
    const firstDoc = centers[0]?.doc
    const other = centers.find((c) => c.doc !== firstDoc)
    if (!other) continue
    const a = centers[0]
    const b = other
    const color = statusColor(checks[checkIdx].status, colors)
    skeletons.push({
      type: 'arrow',
      id: arrowId(checkIdx),
      x: a.cx,
      y: a.cy,
      width: b.cx - a.cx,
      height: b.cy - a.cy,
      points: [
        [0, 0],
        [b.cx - a.cx, b.cy - a.cy],
      ],
      start: { id: a.id },
      end: { id: b.id },
      strokeColor: color,
      strokeStyle: 'dashed',
      label: { text: STATUS_MARK[checks[checkIdx].status], fontSize: 16 },
    })
  }

  // unlocated badges — top-right corner of the doc's first page
  for (const [doc, idxSet] of unlocatedByDoc) {
    const first = [...pages.values()]
      .filter((p) => p.doc === doc)
      .sort((a, b) => a.page - b.page)[0]
    if (!first) continue
    const nums = [...idxSet].sort((a, b) => a - b).map((i) => `#${i + 1}`).join(' ')
    skeletons.push({
      type: 'text',
      id: badgeId(doc),
      x: first.x + first.w - 8,
      y: first.y + 8,
      text: nums,
      fontSize: 16,
      strokeColor: colors.unclear, // token --ochre
      locked: true,
    })
  }

  return skeletons
}

// ── Focus ring ──────────────────────────────────────────────────────────────

/** Thicker-stroke ellipse drawn AROUND the focus target instead of selecting
 *  it (spike trap #2: selection floats the property-panel island over the
 *  canvas). Locked so a click passes through to the evidence underneath; the
 *  overlay swaps the single `ring-focus` element on every focus change. */
export function buildFocusRing(target: Bounds, color: string): Skeleton {
  const pad = 10
  return {
    type: 'ellipse',
    id: RING_ID,
    x: target.x - pad,
    y: target.y - pad,
    width: target.w + pad * 2,
    height: target.h + pad * 2,
    strokeColor: color,
    strokeWidth: 4,
    backgroundColor: 'transparent',
    locked: true,
  }
}
