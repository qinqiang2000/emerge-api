// On-demand translation overlay. Renders one transparent `<button>` per
// translated line as a sibling of the page <img> and the text layer
// (z-index 2). Hotspots are invisible by default — hover/focus reveals an
// ochre tint, and click opens a small popover with the translated text +
// original (smaller) + a copy-to-clipboard button.
//
// The popover itself is rendered into `document.body` via portal so it
// escapes `.dv-pagewrap`'s rotate/zoom transform. Without the portal a
// rotated page would tilt the popover text 90°/180° and a zoomed page
// would scale the popover up/down with the bitmap — both unwanted.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Copy, Check } from 'lucide-react'

import type { TranslateLine } from '../../lib/api'

interface Props {
  lines: TranslateLine[]
  pageW: number
  pageH: number
}

export default function TranslateOverlay({ lines, pageW, pageH }: Props) {
  // Index of the currently-open hotspot (one popover at a time). `null`
  // means closed; ref points at the open hotspot so the popover can
  // measure-and-anchor.
  const [openIdx, setOpenIdx] = useState<number | null>(null)
  const hotspotRefs = useRef<Record<number, HTMLButtonElement | null>>({})

  // Close on Escape, outside-click. Mirrors the existing popover idiom
  // used by ChatHistoryActions.tsx — defer the mousedown listener one
  // tick so the click that opened us doesn't immediately close us.
  useEffect(() => {
    if (openIdx === null) return
    function onClick(e: MouseEvent) {
      const t = e.target as Element | null
      if (
        !t?.closest('.translate-pop') &&
        !t?.closest('.translate-hotspot')
      ) {
        setOpenIdx(null)
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        setOpenIdx(null)
      }
    }
    const id = setTimeout(() => window.addEventListener('mousedown', onClick), 0)
    window.addEventListener('keydown', onKey, true)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [openIdx])

  if (!lines.length || pageW <= 0 || pageH <= 0) return null

  return (
    <div className="translate-overlay" aria-label="translation overlay">
      {lines.map((line, i) => {
        const [x0, y0, x1, y1] = line.bbox
        const left = (x0 / pageW) * 100
        const top = (y0 / pageH) * 100
        const width = ((x1 - x0) / pageW) * 100
        const height = ((y1 - y0) / pageH) * 100
        return (
          <button
            key={i}
            ref={(el) => { hotspotRefs.current[i] = el }}
            type="button"
            className={'translate-hotspot' + (openIdx === i ? ' is-open' : '')}
            aria-label={`翻译: ${line.translated}`}
            aria-expanded={openIdx === i}
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: `${width}%`,
              height: `${height}%`,
            }}
            onClick={(e) => {
              e.stopPropagation()
              setOpenIdx((cur) => (cur === i ? null : i))
            }}
          />
        )
      })}
      {openIdx !== null && hotspotRefs.current[openIdx] && (
        <TranslatePopover
          anchor={hotspotRefs.current[openIdx]!}
          line={lines[openIdx]}
          onClose={() => setOpenIdx(null)}
        />
      )}
    </div>
  )
}

interface PopoverProps {
  anchor: HTMLElement
  line: TranslateLine
  onClose: () => void
}

function TranslatePopover({ anchor, line }: PopoverProps) {
  const popRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const [copied, setCopied] = useState(false)

  // Anchor the popover under (or above) the hotspot in viewport space.
  // Using viewport coords + `position: fixed` keeps it stable on scroll
  // and unaffected by the .dv-pagewrap transform.
  useLayoutEffect(() => {
    const anchorRect = anchor.getBoundingClientRect()
    const popEl = popRef.current
    if (!popEl) return
    const popRect = popEl.getBoundingClientRect()
    const margin = 8
    const vpW = window.innerWidth
    const vpH = window.innerHeight
    let left = anchorRect.left
    let top = anchorRect.bottom + 4
    // Flip above the anchor if there's not enough room below.
    if (top + popRect.height + margin > vpH && anchorRect.top - popRect.height - 4 > margin) {
      top = anchorRect.top - popRect.height - 4
    }
    // Clamp horizontally so the popover stays in the viewport.
    if (left + popRect.width + margin > vpW) {
      left = Math.max(margin, vpW - popRect.width - margin)
    }
    if (left < margin) left = margin
    setPos({ left, top })
  }, [anchor, line])

  async function copyTranslated() {
    try {
      await navigator.clipboard.writeText(line.translated)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Older browsers / insecure contexts: fall back to a hidden
      // textarea + document.execCommand. Best-effort; if both fail the
      // user can still select-and-copy from the DOM text.
      const ta = document.createElement('textarea')
      ta.value = line.translated
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1500)
      } catch { /* swallow */ }
      document.body.removeChild(ta)
    }
  }

  // Initial render: measure invisibly off-screen, then anchor on the
  // next frame. Avoids a one-frame flash at (0,0).
  const style: React.CSSProperties = pos
    ? { left: `${pos.left}px`, top: `${pos.top}px` }
    : { left: '-9999px', top: '-9999px' }

  return createPortal(
    <div
      ref={popRef}
      className="translate-pop"
      role="dialog"
      aria-label="翻译详情"
      style={style}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="translate-pop-translated">{line.translated}</div>
      {line.original && line.original !== line.translated && (
        <div className="translate-pop-original" title="原文">{line.original}</div>
      )}
      <div className="translate-pop-actions">
        <button
          type="button"
          className="translate-pop-copy"
          onClick={copyTranslated}
          title="复制译文"
        >
          {copied ? (
            <>
              <Check size={12} aria-hidden="true" />
              <span>已复制</span>
            </>
          ) : (
            <>
              <Copy size={12} aria-hidden="true" />
              <span>复制</span>
            </>
          )}
        </button>
      </div>
    </div>,
    document.body,
  )
}
