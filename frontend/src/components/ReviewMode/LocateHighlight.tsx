import { useEffect, useMemo, useRef } from 'react'
import { BBoxRect } from './BBoxRect'
import type { FieldLocation } from '../../lib/locate'
import { useLocate } from '../../stores/locate'
import { useT } from '../../i18n'

interface LocateHighlightProps {
  /** All locations for the current doc/tab. */
  locations: FieldLocation[]
  /** Field whose source rects should be painted. */
  focusedPath: string | null
  /** Entity the focused path belongs to — scopes the match in multi-entity docs. */
  focusedEntity: number | null
  /** 1-based page this overlay sits on. */
  page: number
  /** Page size in PDF points (same unit as rects). */
  pageW: number
  pageH: number
}

// Persistent highlight: an ochre *ring* around the value, no fill — a filled
// tint sits over the raster glyphs and occludes the very value it points at
// (the user's "遮挡了金额"), and overlapping rects compound their alpha into a
// near-opaque blob. A ring marks the region while leaving the text fully legible.
// References the semantic token (never raw color, never ochre-soft which is
// transient-menu-only). Purely visual — pointer-events: none.
const HIGHLIGHT_OUTLINE = '2px solid var(--ochre)'

/**
 * Source-grounding highlight layer. Sits above the raster page and below the
 * text layer; paints the focused field's rects on this page. Off-page focus is
 * handled by the caller (field focus handler triggers goPage).
 */
export function LocateHighlight({
  locations,
  focusedPath,
  focusedEntity,
  page,
  pageW,
  pageH,
}: LocateHighlightProps) {
  const t = useT()
  const layerRef = useRef<HTMLDivElement>(null)
  const consumedSeqRef = useRef(0)
  const scrollReq = useLocate((s) => s.scrollReq)
  const rects = useMemo(() => {
    if (!focusedPath || !pageW || !pageH) return []
    const out: { bbox: [number, number, number, number]; key: string }[] = []
    locations.forEach((loc, li) => {
      if (loc.entity_index !== focusedEntity) return
      if (loc.path !== focusedPath) return
      if (loc.page !== page) return
      if (loc.status === 'none') return
      loc.rects.forEach((r, ri) => {
        if (r.length < 4) return
        out.push({ bbox: [r[0], r[1], r[2], r[3]], key: `${li}-${ri}` })
      })
    })
    return out
  }, [locations, focusedPath, focusedEntity, page, pageW, pageH])

  // Auto-pan: when a fresh focus request targets the field whose rects live on
  // THIS page, scroll the first rect to center. Driven by the monotonic
  // `scrollReq.seq` (claimed once per request via `consumedSeqRef`) rather than
  // by mount — so a page lazily scrolled into view later never yanks the user,
  // and the request still fires when an off-page target finishes loading. No
  // zoom change: `scrollIntoView` only translates the viewport.
  useEffect(() => {
    if (!scrollReq || scrollReq.path !== focusedPath) return
    if (scrollReq.seq <= consumedSeqRef.current) return
    if (!rects.length) return // not this page (or rect not painted yet)
    consumedSeqRef.current = scrollReq.seq
    const el = layerRef.current?.querySelector('.dv-locate-rect') as HTMLElement | null
    if (!el) return
    const id = requestAnimationFrame(() => {
      el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' })
    })
    return () => cancelAnimationFrame(id)
  }, [scrollReq, focusedPath, rects])

  if (!rects.length) return null

  return (
    <div
      ref={layerRef}
      className="dv-locate-layer"
      aria-label={t('review.locate.aria')}
      // z-index 0: above the raster <img> (DOM-earlier, auto), below the
      // selectable text layer (.text-layer, z-index 1) so click-to-select
      // still works through it. pointer-events: none — purely visual.
      style={{ position: 'absolute', inset: 0, zIndex: 0, pointerEvents: 'none', overflow: 'hidden' }}
    >
      {rects.map((r) => (
        <BBoxRect
          key={r.key}
          bbox={r.bbox}
          pageW={pageW}
          pageH={pageH}
          className="dv-locate-rect"
          style={{
            outline: HIGHLIGHT_OUTLINE,
            // ring sits just outside the glyph box so it never overlaps the text
            outlineOffset: '1px',
            borderRadius: '2px',
            pointerEvents: 'none',
          }}
        />
      ))}
    </div>
  )
}

export default LocateHighlight
