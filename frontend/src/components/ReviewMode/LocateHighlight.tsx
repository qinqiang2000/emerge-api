import { useMemo } from 'react'
import { BBoxRect } from './BBoxRect'
import type { FieldLocation } from '../../lib/locate'
import { useT } from '../../i18n'

interface LocateHighlightProps {
  /** All locations for the current doc/tab. */
  locations: FieldLocation[]
  /** Field whose source rects should be painted. */
  focusedPath: string | null
  /** 1-based page this overlay sits on. */
  page: number
  /** Page size in PDF points (same unit as rects). */
  pageW: number
  pageH: number
}

// Persistent highlight: ochre outline + low-alpha ochre fill via color-mix so we
// reference the semantic token (never raw color, never ochre-soft which is
// transient-menu-only). Purely visual — pointer-events: none.
const HIGHLIGHT_OUTLINE = '2px solid var(--ochre)'
const HIGHLIGHT_FILL = 'color-mix(in srgb, var(--ochre) 16%, transparent)'

/**
 * Source-grounding highlight layer. Sits above the raster page and below the
 * text layer; paints the focused field's rects on this page. Off-page focus is
 * handled by the caller (field focus handler triggers goPage).
 */
export function LocateHighlight({
  locations,
  focusedPath,
  page,
  pageW,
  pageH,
}: LocateHighlightProps) {
  const t = useT()
  const rects = useMemo(() => {
    if (!focusedPath || !pageW || !pageH) return []
    const out: { bbox: [number, number, number, number]; key: string }[] = []
    locations.forEach((loc, li) => {
      if (loc.path !== focusedPath) return
      if (loc.page !== page) return
      if (loc.status === 'none') return
      loc.rects.forEach((r, ri) => {
        if (r.length < 4) return
        out.push({ bbox: [r[0], r[1], r[2], r[3]], key: `${li}-${ri}` })
      })
    })
    return out
  }, [locations, focusedPath, page, pageW, pageH])

  if (!rects.length) return null

  return (
    <div
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
            outlineOffset: '-1px',
            background: HIGHLIGHT_FILL,
            borderRadius: '2px',
            pointerEvents: 'none',
          }}
        />
      ))}
    </div>
  )
}

export default LocateHighlight
