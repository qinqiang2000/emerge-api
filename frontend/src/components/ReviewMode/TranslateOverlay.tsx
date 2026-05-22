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
import { useT } from '../../i18n'

// ── Ghost layer (inline translated text, decorative only) ───────────────────

interface GhostProps {
  lines: TranslateLine[]
  pageW: number
  pageH: number
}

// Fit-to-bbox sizing: font-size is the SMALLER of two budgets — height (so
// tall headings can grow) and width (so long translations don't truncate).
// With nowrap + ellipsis as a hard fallback, the user almost never sees
// clipped text but the font shrinks gracefully on dense lines. Tuned so
// Chinese reads at roughly the visual weight of the original character.
const SIZING = { minPx: 8, maxPx: 22, heightShrink: 0.85, widthCharFactor: 0.62 } as const

export function TranslateGhost({ lines, pageW, pageH }: GhostProps) {
  if (!lines.length || pageW <= 0 || pageH <= 0) return null
  const sizing = SIZING
  return (
    <div className="translate-ghost-layer" aria-hidden="true">
      {lines.map((line, i) => {
        const [x0, y0, x1, y1] = line.bbox
        const left = (x0 / pageW) * 100
        const top = (y0 / pageH) * 100
        const widthPct = ((x1 - x0) / pageW) * 100
        const heightPct = ((y1 - y0) / pageH) * 100
        // Two budgets:
        //   heightCqh = bbox height × shrink, expressed as "% of layer height" → cqh
        //   widthCqw  = bbox width / (char count × char-width factor), "% of layer width" → cqw
        // Container queries (container-type: size on .translate-ghost-layer)
        // resolve cqh / cqw against the wrapper, which is the rendered page,
        // so the result tracks rotation + zoom for free.
        const heightCqh = heightPct * sizing.heightShrink
        const charCount = Math.max(1, line.translated.length)
        const widthCqw = widthPct / (charCount * sizing.widthCharFactor)
        const fontSize =
          `clamp(${sizing.minPx}px, min(${heightCqh}cqh, ${widthCqw}cqw), ${sizing.maxPx}px)`
        return (
          <span
            key={i}
            className="translate-ghost-span"
            data-line-index={i}
            style={{
              left: `${left}%`,
              top: `${top}%`,
              width: `${widthPct}%`,
              height: `${heightPct}%`,
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
  const t = useT()
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
      aria-label={t('translate.aria.pair')}
      style={style}
      onMouseDown={(e) => e.stopPropagation()}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {showSeparateOriginal && (
        <div className="translate-pop-original-main" title={t('translate.original')}>{line.original}</div>
      )}
      {showTranslation && (
        <div className="translate-pop-translated-sub" title={t('translate.translated')}>{line.translated}</div>
      )}
      <div className="translate-pop-actions">
        <button
          type="button"
          className="translate-pop-copy primary"
          onClick={() => copyText('original')}
          title={t('translate.copy.original')}
          disabled={!line.original}
        >
          {copiedKey === 'original' ? (
            <>
              <Check size={12} aria-hidden="true" />
              <span>{t('translate.copied')}</span>
            </>
          ) : (
            <>
              <Copy size={12} aria-hidden="true" />
              <span>{t('translate.copy.original')}</span>
            </>
          )}
        </button>
        {showTranslation && (
          <button
            type="button"
            className="translate-pop-copy secondary"
            onClick={() => copyText('translated')}
            title={t('translate.copy.translated')}
            aria-label={t('translate.copy.translated')}
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
