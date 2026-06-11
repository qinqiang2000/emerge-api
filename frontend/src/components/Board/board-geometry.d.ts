// Types for `@board-geometry` — the vite alias onto
// backend/app/skills/board_geometry.js, the single source of truth for audit
// board geometry (shared with the MCP Apps iframe board and the Pillow
// renderer; see that file's header for the three ingestion paths).
//
// The target is a CLASSIC script (so board_app.html can inject it verbatim
// into an inline <script>): importing it is side-effect only — it assigns
// `globalThis.BoardGeom` and exports no bindings. These declarations are
// maintained BY HAND; keep them in lockstep with the JS implementation.
//
// NOTE: this file is deliberately a script (no top-level import/export) so
// `declare module '@board-geometry'` is an ambient module declaration, not a
// module augmentation — TS has no resolver for the alias.

declare module '@board-geometry' {
  /** Mirror of the GEOM strict-JSON literal in board_geometry.js. */
  export interface BoardGeomConstants {
    /** board layout scale applied to raster page dims */
    SCALE: number
    /** doc-to-doc band gap (board units) */
    COL_GAP: number
    /** page-to-page stack gap (board units) */
    ROW_GAP: number
    /** pages per sub-column before a doc wraps sideways */
    PAGES_PER_COL: number
    /** padding around an evidence rect so the ellipse doesn't hug glyphs */
    ELLIPSE_PAD: number
    /** arrow shaft standoff from the ellipse rim */
    ARROW_GAP: number
    /** evidence ellipse stroke width (board units) */
    STROKE_W: number
    /** cross-doc arrow stroke width (board units) */
    STROKE_ARROW: number
    /** dash rhythm — on segment */
    DASH_ON: number
    /** dash rhythm — off segment */
    DASH_OFF: number
    /** page raster dpi (textlayer.py::_RENDER_DPI) */
    RENDER_DPI: number
  }

  /** One doc fed into layoutPages. */
  export interface BoardDocInput {
    /** doc filename (group key) */
    name: string
    /** file extension — picks the point→pixel factor (pdf vs raster) */
    ext: string
    /** measured raster dims per page, 1-based page numbers, in source order */
    pages: { page: number; w: number; h: number }[]
  }

  /** One laid-out page in board space. */
  export interface LaidPage {
    doc: string
    page: number
    /** board-space position/size (raster px × scale) */
    x: number
    y: number
    w: number
    h: number
    /** multiply a locate rect coordinate (PDF points for pdf, raster px for
     *  jpg/png) by `k` to get board units: k = pxPerPtFor(ext) × scale */
    k: number
  }

  export interface Bounds {
    x: number
    y: number
    w: number
    h: number
  }

  /** evidenceEllipse result — both consumption shapes at once. */
  export interface EllipseBounds extends Bounds {
    cx: number
    cy: number
    rx: number
    ry: number
  }

  /** rayEllipseTrim result — edge-to-edge arrow shaft endpoints. */
  export interface TrimmedSegment {
    sx: number
    sy: number
    ex: number
    ey: number
  }

  /** anchorForBounds result — board bounds mapped back onto a document page,
   *  rect in SOURCE units (PDF points for pdf docs, raster px for jpg/png). */
  export interface BoardAnchor {
    doc: string
    page: number
    rect: [number, number, number, number]
  }

  export interface BoardGeomApi {
    GEOM: BoardGeomConstants
    pxPerPtFor(ext: string): number
    pageKey(doc: string, page: number): string
    layoutPages(docs: BoardDocInput[], scale?: number): Map<string, LaidPage>
    unionRect(rects: number[][]): Bounds | null
    evidenceEllipse(rects: number[][], page: LaidPage): EllipseBounds | null
    rayEllipseTrim(
      a: { cx: number; cy: number; rx: number; ry: number },
      b: { cx: number; cy: number; rx: number; ry: number },
      gap?: number,
    ): TrimmedSegment | null
    crossDocPairs<T extends { doc: string }>(centers: T[]): [T, T][]
    anchorForBounds(bounds: Bounds, laidPages: Map<string, LaidPage>): BoardAnchor | null
  }

  global {
    // eslint-disable-next-line no-var
    var BoardGeom: BoardGeomApi
  }
}
