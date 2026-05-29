// Transparent text overlay rendered as an absolute-positioned sibling of the
// rasterised page <img>. Each span is positioned in % of the PDF page units;
// the parent (`.dv-pagewrap`) has `position: relative`, so % resolves to the
// rendered image box — rotation + zoom on the wrap come along for free.
//
// Font sizes use `cqh` (container-query-height) so the visible glyphs scale
// with the page height regardless of fit / zoom. The text itself is rendered
// transparent (CSS `color: transparent`) — only the user's selection
// rectangle becomes visible.
//
// The span shape is generic (`SelectableSpan`) so PdfViewer can feed spans
// from EITHER the textlayer sidecar (electronic PDFs) OR derive them from
// translate.lines (vision/scanned mode). Indices align 1-to-1 with
// `translate.lines[i]` in both cases — see PdfViewer.tsx and
// `backend/app/tools/translate.py` (textlayer branch enumerates spans).
//
// bbox -> % positioning is delegated to the shared <BBoxRect> primitive
// (single home for the `(x0/pageW)*100%` formula; see BBoxRect.tsx). This
// layer only owns the cqh font-size + selection styling.

import type { MouseEvent } from 'react'
import { BBoxRect } from './BBoxRect'

export interface SelectableSpan {
  bbox: [number, number, number, number]
  text: string
  font_size: number
}

interface Props {
  spans: SelectableSpan[]
  pageW: number   // PDF page units (points)
  pageH: number
  // Optional hover hooks — used by the translate ghost layer to anchor a
  // popover. The callback receives the span's index (which aligns with
  // `translate.lines`) and the underlying DOM element so the popover can
  // measure-and-anchor in viewport coords.
  onSpanHover?: (index: number, anchorEl: HTMLElement) => void
  onSpanLeave?: (index: number) => void
}

export default function TextLayer({
  spans,
  pageW,
  pageH,
  onSpanHover,
  onSpanLeave,
}: Props) {
  if (!spans.length || pageW <= 0 || pageH <= 0) return null
  return (
    <div className="text-layer" aria-hidden="false">
      {spans.map((s, i) => {
        // font_size is in PDF points; convert to a fraction of the page height
        // so `cqh` (parent is the cq-sized container) renders the glyphs at
        // approximately the same size they appear in the raster. `max(1px, …)`
        // keeps tiny footers selectable even if the page is zoomed out.
        const fontSizePct = (s.font_size / pageH) * 100
        return (
          <BBoxRect
            key={i}
            as="span"
            bbox={s.bbox}
            pageW={pageW}
            pageH={pageH}
            className="text-layer-span"
            data-span-index={i}
            style={{ fontSize: `max(1px, ${fontSizePct}cqh)` }}
            onMouseEnter={onSpanHover ? (e: MouseEvent<HTMLElement>) => onSpanHover(i, e.currentTarget) : undefined}
            onMouseLeave={onSpanLeave ? () => onSpanLeave(i) : undefined}
          >{s.text}</BBoxRect>
        )
      })}
    </div>
  )
}
