// Transparent text overlay rendered as an absolute-positioned sibling of the
// rasterised page <img>. Each span is positioned in % of the PDF page units;
// the parent (`.dv-pagewrap`) has `position: relative`, so % resolves to the
// rendered image box — rotation + zoom on the wrap come along for free.
//
// Font sizes use `cqh` (container-query-height) so the visible glyphs scale
// with the page height regardless of fit / zoom. The text itself is rendered
// transparent (CSS `color: transparent`) — only the user's selection
// rectangle becomes visible.
import type { TextlayerSpan } from '../../lib/api'

interface Props {
  spans: TextlayerSpan[]
  pageW: number   // PDF page units (points)
  pageH: number
}

export default function TextLayer({ spans, pageW, pageH }: Props) {
  if (!spans.length || pageW <= 0 || pageH <= 0) return null
  return (
    <div className="text-layer" aria-hidden="false">
      {spans.map((s, i) => {
        const [x0, y0, x1, y1] = s.bbox
        const left = (x0 / pageW) * 100
        const top = (y0 / pageH) * 100
        const width = ((x1 - x0) / pageW) * 100
        const height = ((y1 - y0) / pageH) * 100
        // font_size is in PDF points; convert to a fraction of the page height
        // so `cqh` (parent is the cq-sized container) renders the glyphs at
        // approximately the same size they appear in the raster. `max(1px, …)`
        // keeps tiny footers selectable even if the page is zoomed out.
        const fontSizePct = (s.font_size / pageH) * 100
        return (
          <span
            key={i}
            className="text-layer-span"
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: `${width}%`,
              height: `${height}%`,
              fontSize: `max(1px, ${fontSizePct}cqh)`,
            }}
          >{s.text}</span>
        )
      })}
    </div>
  )
}
