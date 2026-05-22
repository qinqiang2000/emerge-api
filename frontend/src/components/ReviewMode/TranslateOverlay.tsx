// Translation overlay — TWO pieces that callers consume separately:
//
//   1. <TranslateGhost>  Inline translated text rendered as a passive,
//      pointer-events: none layer above the PDF raster. It is purely
//      decorative wayfinding — "here's which lines say what" — and MUST
//      NOT capture mouse / selection events. The transparent text layer
//      (z=1, pointer-events: auto) still owns rubberband selection of
//      the ORIGINAL text underneath.
//
//   2. <TranslatePopover>  A portal'd, viewport-fixed bubble anchored to
//      the currently-hovered text-layer span. Primary action is "复制原文"
//      because the original text is what users paste back into entity
//      fields during review; the translated string is shown smaller, as
//      a navigator subtitle.
//
// The hover handoff is owned by PdfViewer: TextLayer fires onSpanHover(i,
// el), PdfViewer threads (i, el) into TranslatePopover. The ghost layer
// never receives hover events.
//
// Index alignment invariant: `translate.lines[i]` corresponds to
// `text_layer.spans[i]` for both rendering modes. In textlayer mode the
// backend (`backend/app/tools/translate.py`) iterates spans by
// enumerate(); in vision mode the text-layer spans ARE derived from
// translate.lines so they share the same array. This lets PdfViewer
// look up the popover content by index alone — no bbox matching needed.
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Copy, Check } from 'lucide-react'

import type { TranslateLine } from '../../lib/api'

// ── Ghost layer (inline translated text, decorative only) ───────────────────

interface GhostProps {
  lines: TranslateLine[]
  pageW: number
  pageH: number
  /** `subtle` = navigator (small low-alpha annotations above original raster);
   *  `cover` = reading mode (opaque larger Chinese visually replacing the
   *  raster, Chrome / WeChat style). Both render via the same DOM tree —
   *  CSS class flips fonts, alpha, and background. Original text remains
   *  selectable via the textlayer at z=1 in BOTH modes (ghost is z=2 +
   *  pointer-events:none so events fall through to the textlayer). */
  view?: 'subtle' | 'cover'
}

// Per-view font sizing tables. Cover mode wants Chinese to read at roughly
// the visual weight of the original character; subtle mode wants the
// opposite — small annotation that yields to the raster underneath.
const GHOST_SIZING = {
  subtle: { minPx: 8, maxPx: 11, shrink: 0.5 },
  cover:  { minPx: 11, maxPx: 24, shrink: 0.85 },
} as const

export function TranslateGhost({ lines, pageW, pageH, view = 'subtle' }: GhostProps) {
  if (!lines.length || pageW <= 0 || pageH <= 0) return null
  const sizing = GHOST_SIZING[view]
  return (
    <div className={`translate-ghost-layer is-${view}`} aria-hidden="true">
      {lines.map((line, i) => {
        const [x0, y0, x1, y1] = line.bbox
        const left = (x0 / pageW) * 100
        const top = (y0 / pageH) * 100
        const width = ((x1 - x0) / pageW) * 100
        const height = ((y1 - y0) / pageH) * 100
        // Same `cqh` trick as the text layer so font scales with the
        // rendered page. We use the bbox HEIGHT as the font reference so
        // tall/short lines pick proportional sizes; clamp() then enforces
        // the px caps. cqh on the wrapper (set by .translate-ghost-layer
        // container-type:size) resolves to "% of layer height".
        const fontSizeCqh = ((y1 - y0) / pageH) * 100 * sizing.shrink
        const fontSize =
          `clamp(${sizing.minPx}px, ${fontSizeCqh}cqh, ${sizing.maxPx}px)`
        return (
          <span
            key={i}
            className="translate-ghost-span"
            data-line-index={i}
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: `${width}%`,
              height: `${height}%`,
              fontSize,
            }}
          >
            {line.translated}
          </span>
        )
      })}
    </div>
  )
}

// ── Popover (portal'd to document.body, viewport-fixed) ────────────────────

interface PopoverProps {
  anchor: HTMLElement
  line: TranslateLine
  onClose: () => void
  onMouseEnter?: () => void
  onMouseLeave?: () => void
}

export function TranslatePopover({
  anchor,
  line,
  onClose,
  onMouseEnter,
  onMouseLeave,
}: PopoverProps) {
  const popRef = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const [copiedKey, setCopiedKey] = useState<null | 'original' | 'translated'>(null)

  // Anchor the popover under (or above) the hovered span in viewport
  // space. Using viewport coords + `position: fixed` keeps it stable on
  // scroll and unaffected by the .dv-pagewrap transform.
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
    if (top + popRect.height + margin > vpH && anchorRect.top - popRect.height - 4 > margin) {
      top = anchorRect.top - popRect.height - 4
    }
    if (left + popRect.width + margin > vpW) {
      left = Math.max(margin, vpW - popRect.width - margin)
    }
    if (left < margin) left = margin
    setPos({ left, top })
  }, [anchor, line])

  // Esc closes; outside-click closes. Defer the mousedown listener one
  // tick so the click that surfaced us (via hover) doesn't immediately
  // close us. Mirrors the existing popover idiom used elsewhere.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      const t = e.target as Element | null
      if (!t?.closest('.translate-pop') && !t?.closest('.text-layer-span')) {
        onClose()
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    const id = setTimeout(() => window.addEventListener('mousedown', onClick), 0)
    window.addEventListener('keydown', onKey, true)
    return () => {
      clearTimeout(id)
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [onClose])

  async function copyText(key: 'original' | 'translated') {
    const text = key === 'original' ? line.original : line.translated
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setCopiedKey(key)
      window.setTimeout(() => setCopiedKey(null), 1500)
    } catch {
      // Insecure context / older browsers — fall back to hidden textarea.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        setCopiedKey(key)
        window.setTimeout(() => setCopiedKey(null), 1500)
      } catch { /* swallow */ }
      document.body.removeChild(ta)
    }
  }

  const style: React.CSSProperties = pos
    ? { left: `${pos.left}px`, top: `${pos.top}px` }
    : { left: '-9999px', top: '-9999px' }

  // UX hierarchy: original on top (the high-value asset users copy and
  // paste back into entity fields), translation below as a smaller
  // navigator subtitle. "复制原文" is the primary copy button; "译文"
  // gets a secondary icon-only button on the same action row.
  const showSeparateOriginal = !!line.original
  const showTranslation = !!line.translated && line.translated !== line.original

  return createPortal(
    <div
      ref={popRef}
      className="translate-pop"
      role="dialog"
      aria-label="原文与翻译"
      style={style}
      onMouseDown={(e) => e.stopPropagation()}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {showSeparateOriginal && (
        <div className="translate-pop-original-main" title="原文">{line.original}</div>
      )}
      {showTranslation && (
        <div className="translate-pop-translated-sub" title="译文">{line.translated}</div>
      )}
      <div className="translate-pop-actions">
        <button
          type="button"
          className="translate-pop-copy primary"
          onClick={() => copyText('original')}
          title="复制原文"
          disabled={!line.original}
        >
          {copiedKey === 'original' ? (
            <>
              <Check size={12} aria-hidden="true" />
              <span>已复制</span>
            </>
          ) : (
            <>
              <Copy size={12} aria-hidden="true" />
              <span>复制原文</span>
            </>
          )}
        </button>
        {showTranslation && (
          <button
            type="button"
            className="translate-pop-copy secondary"
            onClick={() => copyText('translated')}
            title="复制译文"
            aria-label="复制译文"
          >
            {copiedKey === 'translated' ? (
              <Check size={11} aria-hidden="true" />
            ) : (
              <Copy size={11} aria-hidden="true" />
            )}
          </button>
        )}
      </div>
    </div>,
    document.body,
  )
}

// Back-compat default export: re-export the ghost layer as the default so
// any straggler imports still work during the refactor. Callers should
// prefer the named exports going forward.
export default TranslateGhost
