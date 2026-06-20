// boardScene — the excalidraw DIALECT layer for the audit board.
//
// Geometry (layout, unit conversion, evidence mapping, arrow trimming) lives
// in the shared single source `backend/app/skills/board_geometry.js` —
// side-effect-imported below via the `@board-geometry` vite alias and read
// off `globalThis.BoardGeom` (the same file is injected verbatim into the
// MCP Apps iframe board and parsed by the Pillow renderer; see its header).
// This module keeps what is excalidraw-specific: skeleton assembly, the id
// contract, colors — plus thin re-exports so consumers/tests keep one import.
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

import '@board-geometry'
import type { BoardDocInput, Bounds, LaidPage } from '@board-geometry'

// type-only (erased at compile) — the pure layer stays fetch-free; the wire
// contract for board_notes annotations lives with its payload in lib/api.
import type { BoardAnnotation } from '../../lib/api'

const G = globalThis.BoardGeom

/** One excalidraw element skeleton — kept structurally untyped so this module
 *  never imports from `@excalidraw/excalidraw` (the pure layer must not pull
 *  the 1.5MB canvas dep into test or main bundles). */
export type Skeleton = Record<string, unknown>

// ── Shared geometry re-exports (single source: board_geometry.js) ───────────

export type { BoardAnchor, BoardDocInput, Bounds, LaidPage } from '@board-geometry'

export const LAYOUT_SCALE = G.GEOM.SCALE
export const COL_GAP = G.GEOM.COL_GAP
export const ROW_GAP = G.GEOM.ROW_GAP

/** Padding (board units) around an evidence rect so the ellipse doesn't hug
 *  the glyphs. Same value the spike used. */
export const ELLIPSE_PAD = G.GEOM.ELLIPSE_PAD

/** PDF point → raster pixel factor (page rasters render at GEOM.RENDER_DPI,
 *  see board_geometry.js for the textlayer.py lockstep note). */
export const PX_PER_PT = G.GEOM.RENDER_DPI / 72

export const pxPerPtFor = G.pxPerPtFor
export const pageKey = G.pageKey

/** Pages per sub-column before a doc wraps sideways — keeps a many-paged doc
 *  from stretching the board into a strip (an 18-page doc degraded
 *  fit-to-viewport to ~10% zoom, prod dogfood 2026-06-11). */
export const PAGES_PER_COL = G.GEOM.PAGES_PER_COL

/** One column band per doc, pages stacked top-to-bottom and wrapping into
 *  sub-columns of PAGES_PER_COL (ROW_GAP apart). The doc-to-doc COL_GAP stays
 *  wider so docs still read as groups. */
export const layoutPages = G.layoutPages

/** Board bounds → (doc, page, source-unit rect) reverse mapping — anchors a
 *  user doodle back onto the document it was drawn over (plan §D). */
export const anchorForBounds = G.anchorForBounds

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
  /** token --paper — the page-placeholder fill (a blank page reads as paper
   *  sitting on the paper-2 canvas while its raster streams in) */ page: string
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
    // Evidence marks are FIXED vivid inks, deliberately NOT the paper-muted
    // chrome tokens: annotations must stand out against arbitrary document
    // pixels, and the muted moss read as "不够醒目" in dogfood (2026-06-11).
    // pass/fail share ONE marker hue — on the board the question is WHERE
    // the evidence sits; the verdict lives on the rail's ✓/✗ and the
    // single-pair arrow label. MAGENTA, because it virtually never occurs in
    // business documents: red/orange camouflage on red brand pages (KFC
    // posters), blue reads thin on white, amber collides with yellow
    // highlights (all three tried in dogfood 2026-06-11). unclear stays
    // amber — "couldn't read it" is a different signal than a mark.
    pass: '#d6219c',
    fail: '#d6219c',
    unclear: '#d97706',
    chrome: cssVar('--ink-3', '#6b6258'),
    canvas: cssVar('--paper-2', '#faf8f4'),
    page: cssVar('--paper', '#fffdf9'),
  }
}

export type CheckStatus = 'pass' | 'fail' | 'unclear'

export function statusColor(status: CheckStatus, colors: BoardColors): string {
  return status === 'pass' ? colors.pass : status === 'fail' ? colors.fail : colors.unclear
}

const STATUS_MARK: Record<CheckStatus, string> = { pass: '✓', fail: '✗', unclear: '?' }

// ── Page ordering (board policy, not geometry) ──────────────────────────────

/** Reorder a doc's pages so the cited ones come first (band's leading
 *  sub-column). For a many-paged doc whose cited page sits deep in the grid,
 *  doc-level adjacency isn't enough — the circle would still be a whole band
 *  away from the other doc (dogfood 2026-06-11). Page captions carry the real
 *  page numbers, so a non-sequential grid stays self-describing. */
export function pullPagesFront(doc: BoardDocInput, cited: number[]): BoardDocInput {
  if (!cited.length) return doc
  const front = doc.pages.filter((p) => cited.includes(p.page))
  if (!front.length) return doc
  return { ...doc, pages: [...front, ...doc.pages.filter((p) => !cited.includes(p.page))] }
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

/** Page PLACEHOLDERS: a blank-page rectangle (same id + bounds the image will
 *  take) + caption per page. Drawn instantly so the board has structure before
 *  any raster downloads; BoardOverlay swaps each rectangle for its image (same
 *  id) as the raster streams in.
 *
 *  Why a rectangle and not the image skeleton up front: `convertToExcalidrawElements`
 *  DROPS an image skeleton whose file isn't registered yet — and loses the rest
 *  of the batch with it (prod dogfood 2026-06-20: committing image skeletons
 *  before `addFiles` left the whole canvas blank). Rectangles need no file, so
 *  the structure always survives; the image is converted per-page only AFTER
 *  its `addFiles`, which is the proven render path. */
export function buildPagePlaceholders(pages: LaidPage[], colors: BoardColors): Skeleton[] {
  const skeletons: Skeleton[] = []
  for (const p of pages) {
    skeletons.push({
      type: 'rectangle',
      id: imgId(p.doc, p.page),
      x: p.x,
      y: p.y,
      width: p.w,
      height: p.h,
      strokeColor: colors.chrome, // token --ink-3 (thin page edge)
      backgroundColor: colors.page, // token --paper (blank page fill)
      fillStyle: 'solid',
      strokeWidth: 1,
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

/** Union {x,y,w,h} boxes — historical boardScene shape; delegates to the
 *  shared unionRect (which speaks [x0,y0,x1,y1] lists). */
export function unionBounds(boxes: Bounds[]): Bounds | null {
  return G.unionRect(boxes.map((b) => [b.x, b.y, b.x + b.w, b.y + b.h]))
}

/** Board-space bounds of one located evidence: union the (possibly multi-line)
 *  rects, convert source units → board units via the page's `k`, offset by the
 *  page position, pad. Same `(imgX + x0·k)` mapping as the spike / BBoxRect.
 *  Thin wrapper over the shared evidenceEllipse, narrowed to the Bounds shape
 *  excalidraw skeletons consume. */
export function evidenceBounds(rects: number[][], page: LaidPage): Bounds | null {
  const e = G.evidenceEllipse(rects, page)
  return e && { x: e.x, y: e.y, w: e.w, h: e.h }
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
  const centersByCheck = new Map<number, { doc: string; cx: number; cy: number; rx: number; ry: number; id: string }[]>()

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
    const b = G.evidenceEllipse(ev.rects, page)
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
      strokeWidth: G.GEOM.STROKE_W,
      // Dashed outline, NO fill (user 2026-06-11: fill covered the text).
      // Spike trap #4 (clickable interior) no longer applies — overlays are
      // shown for the ACTIVE check only and the rail drives focus, so the
      // canvas shapes don't need to be click targets.
      strokeStyle: 'dashed',
      backgroundColor: 'transparent',
    })
    let centers = centersByCheck.get(ev.checkIdx)
    if (!centers) { centers = []; centersByCheck.set(ev.checkIdx, centers) }
    centers.push({ doc: ev.doc, cx: b.cx, cy: b.cy, rx: b.rx, ry: b.ry, id })
  }

  // cross-doc arrows — one per CONSECUTIVE cross-doc evidence pair (greedy
  // stride-2 pairing, see crossDocPairs in board_geometry.js). The shaft runs
  // ELLIPSE EDGE to ellipse edge (+gap), via the shared rayEllipseTrim — the
  // skeleton `start`/`end` bindings don't retrim programmatic scenes, so a
  // center-to-center shaft ran straight through the circled text and parked
  // the arrowhead ON it (dogfood 2026-06-11).
  for (const [checkIdx, centers] of centersByCheck) {
    const pairs = G.crossDocPairs(centers)
    const color = statusColor(checks[checkIdx].status, colors)
    pairs.forEach(([a, b], k) => {
      const seg = G.rayEllipseTrim(a, b, G.GEOM.ARROW_GAP)
      if (!seg) return
      const { sx, sy, ex, ey } = seg
      skeletons.push({
        type: 'arrow',
        // first pair keeps the bare arrow-{checkIdx} id (rail lookups, tests);
        // extra pairs suffix -{k} — checkIdxOfElementId parses both.
        id: k === 0 ? arrowId(checkIdx) : `${arrowId(checkIdx)}-${k}`,
        x: sx,
        y: sy,
        width: ex - sx,
        height: ey - sy,
        points: [
          [0, 0],
          [ex - sx, ey - sy],
        ],
        strokeColor: color,
        strokeWidth: G.GEOM.STROKE_ARROW,
        strokeStyle: 'dashed',
        // one pair → keep the ✓/✗ label; a 9-arrow fan with 9 labels is noise
        // (the rail row + circle colors already carry the verdict)
        ...(pairs.length === 1
          ? { label: { text: STATUS_MARK[checks[checkIdx].status], fontSize: 16 } }
          : {}),
      })
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

// ── User-note annotations (D1: doodle → teaching signal) ───────────────────

export type { BoardAnnotation } from '../../lib/api'

/** The structural slice of an excalidraw element that annotation needs —
 *  every element type carries the bounds quad (point-like elements may have
 *  width/height 0); only text elements carry `text`. */
export interface UserElementLike {
  id: string
  type: string
  x: number
  y: number
  width: number
  height: number
  text?: string
}

/** Anchor each user-drawn element back onto the document page it sits over
 *  (center-point page hit via the shared anchorForBounds). A doodle in empty
 *  board space still yields an annotation — doc/page/rect stay null and the
 *  backend digest renders it as a blank-space note. Rects are SOURCE units
 *  and never leave the render layer (red line: the backend digests them to
 *  text before any agent sees them). */
export function annotateUserElements(
  elements: readonly UserElementLike[],
  laidPages: Map<string, LaidPage>,
): BoardAnnotation[] {
  return elements.map((e) => {
    const kind: BoardAnnotation['kind'] =
      e.type === 'text' ? 'text' : e.type === 'freedraw' ? 'draw' : 'shape'
    const a = anchorForBounds({ x: e.x, y: e.y, w: e.width, h: e.height }, laidPages)
    const out: BoardAnnotation = {
      id: e.id,
      kind,
      doc: a ? a.doc : null,
      page: a ? a.page : null,
      rect: a ? a.rect : null,
    }
    if (kind === 'text' && typeof e.text === 'string') out.text = e.text
    return out
  })
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
