import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { Languages, MapPinOff } from 'lucide-react'
import { pdfPageUrl } from '../../lib/api'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'
import { useTextlayer } from '../../stores/textlayer'
import { useTranslate } from '../../stores/translate'
import TextLayer, { type SelectableSpan } from './TextLayer'
import { TranslateGhost, TranslatePopover } from './TranslateOverlay'
import { LocateHighlight } from './LocateHighlight'
import { useLocate } from '../../stores/locate'
import { useT } from '../../i18n'

// Toolbar tooltip: native `title=` has a ~500–1500ms OS-level delay that
// makes the dv-toolbar feel sluggish. Radix tooltip with a short delay
// gives the Mac-feel pop the rest of this UI assumes.
const TOOLBAR_TIP_DELAY_MS = 120

function Tip({ label, children }: { label: string; children: ReactElement }) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content className="dv-tip" sideOffset={6} side="bottom">
          {label}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

// Hover popover timing — feels like a Mac OS tooltip, not a flicker on
// mouse-traverse.
const POPOVER_OPEN_DELAY_MS = 250
const POPOVER_CLOSE_DELAY_MS = 200

// State of the currently-anchored popover. Keyed by page + line index so
// only one popover ever shows, even if user mouses across pages.
type PopoverState = {
  page: number
  index: number
  anchor: HTMLElement
}

export default function PdfViewer() {
  const t = useT()
  const { activeProjectId, activeFilename, page, pageCount, setPageCount } = useReview()
  const activeTabKey = useReview((s) => s.activeTabKey)
  const { byProject } = useDocs()
  // Translate mode is driven by both the toolbar button and the `T` key
  // — subscribe so the button reflects state changes from either path.
  const translateMode = useTranslate((s) => s.mode)
  const translateByKey = useTranslate((s) => s.byKey)
  // Textlayer state — the translate-button spinner doubles as a generic
  // "this page is still being processed by the backend" indicator. The
  // /textlayer endpoint runs OCR (5e02a42) and takes seconds the first
  // time a page is opened; without this the user sees a static button
  // and has no idea text-selection isn't ready yet.
  const textlayerByKey = useTextlayer((s) => s.byKey)

  const [visiblePage, setVisiblePage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [rot, setRot] = useState(0) // 0 | 90 | 180 | 270
  const [fit, setFit] = useState(true)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set([1]))
  const [vpW, setVpW] = useState(600)
  const [aspectRatio, setAspectRatio] = useState(11 / 8.5)
  // The single popover instance — null when nothing hovered.
  const [popover, setPopover] = useState<PopoverState | null>(null)

  // ── Source-grounding focus status (drives the "where is it?" hint) ─────────
  // When a field is focused but its source can't be located in the doc, the
  // viewer would otherwise sit silent and the reviewer hunts page by page.
  // Surface a transient pane-anchored hint instead. Located fields need no
  // hint — the pan + ring already answer "where".
  const focusedPath = useLocate((s) => s.focusedPath)
  const focusedEntity = useLocate((s) => s.focusedEntity)
  const locateLoading = useLocate((s) => s.loading)
  const locations = useLocate((s) =>
    activeFilename ? s.byKey[`${activeFilename}::${activeTabKey}`] : undefined,
  )
  const focusStatus = useMemo<'none' | 'resolving' | 'located' | 'unlocated'>(() => {
    if (!focusedPath) return 'none'
    if (!locations) return locateLoading ? 'resolving' : 'unlocated'
    // Scope to the focused entity — the same path repeats per entity.
    const hits = locations.filter((l) => l.entity_index === focusedEntity && l.path === focusedPath)
    if (hits.some((l) => l.status !== 'none' && l.rects.length > 0 && l.page != null)) return 'located'
    if (hits.length === 0 && locateLoading) return 'resolving'
    return 'unlocated'
  }, [focusedPath, focusedEntity, locations, locateLoading])

  // The hint mirrors focusStatus directly: shown while an unlocated/resolving
  // field stays focused, cleared the moment focus moves or the source resolves.
  // (No setTimeout auto-dismiss — a timer inside this effect got cleared early
  // under React's effect re-runs, and persist-while-focused is the cleaner
  // contract anyway: the pill is the answer to "where's the source?", so it
  // belongs on screen exactly as long as that field is the focused one.)
  const locateHint: 'resolving' | 'unlocated' | null =
    focusStatus === 'unlocated' ? 'unlocated' : focusStatus === 'resolving' ? 'resolving' : null

  const viewportRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  // Timers for hover-debounced popover open/close, indexed by intent so
  // we can cancel the right one on a follow-up event.
  const openTimerRef = useRef<number | null>(null)
  const closeTimerRef = useRef<number | null>(null)

  function clearOpenTimer() {
    if (openTimerRef.current !== null) {
      window.clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
  }
  function clearCloseTimer() {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }

  // Sync pageCount from doc store. `activeFilename` is the on-disk filename
  // (the only doc handle now); look up by `filename` field.
  useEffect(() => {
    if (!activeProjectId || !activeFilename) return
    const doc = byProject[activeProjectId]?.find(d => d.filename === activeFilename)
    if (doc?.page_count) setPageCount(doc.page_count)
  }, [activeProjectId, activeFilename, byProject, setPageCount])

  // Reset on doc change
  useEffect(() => {
    setVisiblePage(1)
    setZoom(1)
    setRot(0)
    setFit(true)
    setLoadedPages(new Set([1]))
    setAspectRatio(11 / 8.5)
    setPopover(null)
    pageRefs.current = {}
    clearOpenTimer()
    clearCloseTimer()
  }, [activeFilename])

  // Track viewport inner width for rotation-aware fit
  useEffect(() => {
    const vp = viewportRef.current
    if (!vp) return
    const measure = () => {
      const cs = getComputedStyle(vp)
      const padL = parseFloat(cs.paddingLeft) || 0
      const padR = parseFloat(cs.paddingRight) || 0
      setVpW(Math.max(120, vp.clientWidth - padL - padR))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(vp)
    return () => ro.disconnect()
  }, [activeFilename])

  // Auto-scroll to page when store.page changes (field click → goPage)
  useEffect(() => {
    const el = pageRefs.current[page]
    const vp = viewportRef.current
    if (el && vp) vp.scrollTo({ top: el.offsetTop - 14, behavior: 'smooth' })
  }, [page])

  // IntersectionObserver for lazy loading
  useEffect(() => {
    const vp = viewportRef.current
    if (!vp || pageCount === 0) return
    const obs = new IntersectionObserver((entries) => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          const p = Number((e.target as HTMLElement).dataset.page)
          if (p) setLoadedPages(prev => { const next = new Set(prev); next.add(p); return next })
        }
      })
    }, { root: vp, rootMargin: '300px' })
    Object.entries(pageRefs.current).forEach(([, el]) => { if (el) obs.observe(el) })
    return () => obs.disconnect()
  }, [pageCount, activeFilename])

  // Scroll → update visible page indicator. Closing the popover on scroll
  // avoids stale anchors leaving the popover floating after the source
  // span has scrolled out of view.
  useEffect(() => {
    const vp = viewportRef.current
    if (!vp) return
    const onScroll = () => {
      let best = 1, bestDist = Infinity
      for (let i = 1; i <= pageCount; i++) {
        const el = pageRefs.current[i]
        if (!el) continue
        const dist = Math.abs(el.getBoundingClientRect().top - (vp.getBoundingClientRect().top + 20))
        if (dist < bestDist) { bestDist = dist; best = i }
      }
      setVisiblePage(best)
      if (popover) {
        clearOpenTimer()
        clearCloseTimer()
        setPopover(null)
      }
    }
    vp.addEventListener('scroll', onScroll, { passive: true })
    return () => vp.removeEventListener('scroll', onScroll)
  }, [pageCount, popover])

  function jumpToPage(p: number) {
    const el = pageRefs.current[p]
    const vp = viewportRef.current
    if (el && vp) vp.scrollTo({ top: el.offsetTop - 14, behavior: 'smooth' })
  }

  function rotate(dir: number) {
    setRot(r => (r + (dir > 0 ? 90 : -90) + 360) % 360)
  }

  const isRot = rot !== 0
  const pageH = vpW * aspectRatio
  // When rotated 90/270, the page's visual width = its height → scale to fit
  const fitZoom = isRot ? Math.min(3, Math.max(0.2, +(vpW / pageH).toFixed(3))) : 1
  const effZoom = fit ? fitZoom : zoom

  function bumpZoom(d: number) {
    const base = fit ? fitZoom : zoom
    setFit(false)
    setZoom(Math.max(0.2, Math.min(3, +(base + d).toFixed(2))))
  }

  // Translate after rotation to keep top-left-origin content inside the sizer
  function wrapXform(): React.CSSProperties {
    const W = vpW * effZoom, H = pageH * effZoom
    let tx = 0, ty = 0
    if (rot === 90) { tx = H; ty = 0 }
    else if (rot === 180) { tx = W; ty = H }
    else if (rot === 270) { tx = 0; ty = W }
    return {
      transform: `translate(${tx}px, ${ty}px) rotate(${rot}deg) scale(${effZoom})`,
      transformOrigin: 'top left',
      width: `${vpW}px`,
    }
  }

  // Outer sizer reserves the correct layout space for the rotated page
  function sizerStyle(): React.CSSProperties {
    const w = isRot ? pageH : vpW
    const h = isRot ? vpW : pageH
    return { width: `${w * effZoom}px`, height: `${h * effZoom}px`, position: 'relative' }
  }

  // Compute toolbar button visual state from the per-page translate
  // payloads scoped to the active doc. `any-loading` wins (shows
  // spinner), then `any-ready` (ochre tint), then `all-error` (rose).
  // Idle when mode === 'off' (nothing fired yet) or when only idle keys
  // exist for this doc.
  const docKeyPrefix = activeProjectId && activeFilename
    ? `${activeProjectId}::${activeFilename}::`
    : null
  type TranslateBtnState = 'idle' | 'loading' | 'ready' | 'error'
  let translateBtnState: TranslateBtnState = 'idle'
  let translateBtnError: string | null = null
  if (translateMode !== 'off' && docKeyPrefix) {
    let anyLoading = false
    let anyReady = false
    let anyError = false
    let lastError: string | null = null
    for (const [k, v] of Object.entries(translateByKey)) {
      if (!k.startsWith(docKeyPrefix)) continue
      if (v.kind === 'loading') anyLoading = true
      else if (v.kind === 'ready') anyReady = true
      else if (v.kind === 'error') { anyError = true; lastError = v.message }
    }
    if (anyLoading) translateBtnState = 'loading'
    else if (anyReady) translateBtnState = 'ready'
    else if (anyError) { translateBtnState = 'error'; translateBtnError = lastError }
  }
  // Overload: if translate mode is off (or its state is idle/ready), and
  // the visible page's textlayer is still being fetched (OCR running),
  // surface that as the same `loading` spinner. The button thus acts as
  // a single "page-still-processing" indicator — translate mode itself
  // doesn't change, just the visual state.
  if (translateBtnState !== 'loading' && docKeyPrefix) {
    const visibleKey = `${docKeyPrefix}${visiblePage}`
    if (textlayerByKey[visibleKey]?.kind === 'loading') {
      translateBtnState = 'loading'
    }
  }

  function onToggleTranslate() {
    if (!activeProjectId || !activeFilename) return
    // T-key + toolbar both toggle: off ↔ cover.
    useTranslate.getState().toggleMode()
    const after = useTranslate.getState().mode
    if (after !== 'off') {
      // Fan-out: trigger ensure() for every currently-loaded page. New
      // pages scrolled into view after this will trigger via the per-page
      // host component below.
      const ensure = useTranslate.getState().ensure
      for (const p of loadedPages) {
        ensure(activeProjectId, activeFilename, p)
      }
    } else {
      // Flipping mode off → close any open popover so it doesn't linger
      // attached to a span the user can no longer see translated.
      setPopover(null)
      clearOpenTimer()
      clearCloseTimer()
    }
  }

  // Keyboard shortcuts: `t` toggles translate mode (with fan-out), and
  // `Shift+T` force-retranslates the page the user is currently looking
  // at (bypasses both frontend session cache and backend sidecar).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Bail if focus is inside any editable target — otherwise every `t`
      // typed into the chat composer would toggle the overlay.
      const t = e.target as HTMLElement | null
      const tag = t?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || t?.isContentEditable) return
      if (!activeProjectId || !activeFilename) return

      // Shift+T: force re-translate the currently focused page.
      if (e.key === 'T' && e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault()
        // Force a re-translate; if mode is off, flip it on first so the
        // `ensure` guard in the store accepts the call.
        const st = useTranslate.getState()
        if (st.mode === 'off') st.setMode('cover')
        useTranslate.getState().ensure(activeProjectId, activeFilename, page, { force: true })
        return
      }
      // Plain `t`: toggle mode + fan out to loaded pages on switch-on.
      if (e.key === 't' && !e.shiftKey && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault()
        onToggleTranslate()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // `onToggleTranslate` closes over `loadedPages` — re-bind whenever
    // it changes so newly-loaded pages get fanned out on the next `t`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId, activeFilename, page, loadedPages])

  // ── Hover wiring ─────────────────────────────────────────────────────────
  // Each per-page text layer calls these with its own page number bound,
  // so the popover state always knows which page's translate.lines to
  // look up. We keep one popover instance globally — moving to a span on
  // a different page just re-anchors.

  const openPopoverSoon = useCallback((page: number, index: number, anchor: HTMLElement) => {
    // Cancel any pending close — user is back hovering a real span.
    clearCloseTimer()
    // If we already have a popover open on this exact span, no-op.
    if (popover && popover.page === page && popover.index === index) {
      return
    }
    clearOpenTimer()
    openTimerRef.current = window.setTimeout(() => {
      openTimerRef.current = null
      setPopover({ page, index, anchor })
    }, POPOVER_OPEN_DELAY_MS)
  }, [popover])

  const scheduleClose = useCallback(() => {
    // Cancel any pending open — the user moved away before tooltip
    // materialized.
    clearOpenTimer()
    clearCloseTimer()
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null
      setPopover(null)
    }, POPOVER_CLOSE_DELAY_MS)
  }, [])

  // Popover stays open while pointer is over IT. Cancel the close grace.
  const onPopoverMouseEnter = useCallback(() => {
    clearCloseTimer()
  }, [])
  const onPopoverMouseLeave = useCallback(() => {
    scheduleClose()
  }, [scheduleClose])

  const onPopoverClose = useCallback(() => {
    clearOpenTimer()
    clearCloseTimer()
    setPopover(null)
  }, [])

  // Look up the translate line for the currently-pinned popover, if any.
  // The lookup gates render: only show popover if the corresponding
  // translate state is ready AND has a line at that index.
  const popoverLine = useMemo(() => {
    if (!popover || !activeProjectId || !activeFilename) return null
    const key = `${activeProjectId}::${activeFilename}::${popover.page}`
    const state = translateByKey[key]
    if (!state || state.kind !== 'ready') return null
    return state.payload.lines[popover.index] ?? null
  }, [popover, activeProjectId, activeFilename, translateByKey])

  if (!activeProjectId || !activeFilename) return null

  return (
    <>
      <TooltipPrimitive.Provider delayDuration={TOOLBAR_TIP_DELAY_MS} skipDelayDuration={0}>
        <div className="dv-toolbar">
          <Tip label={t('pdf.prevPage')}>
            <button className="dv-btn"
              disabled={visiblePage <= 1 || pageCount <= 1}
              onClick={() => jumpToPage(Math.max(1, visiblePage - 1))}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9,3 4,7 9,11"/></svg>
            </button>
          </Tip>
          <span className="dv-page">
            <input
              value={visiblePage}
              onChange={e => {
                const v = parseInt(e.target.value) || 1
                jumpToPage(Math.max(1, Math.min(pageCount, v)))
              }}
              disabled={pageCount <= 1}
            />
            <span className="of">/</span>
            <span className="tot">{pageCount}</span>
          </span>
          <Tip label={t('pdf.nextPage')}>
            <button className="dv-btn"
              disabled={visiblePage >= pageCount || pageCount <= 1}
              onClick={() => jumpToPage(Math.min(pageCount, visiblePage + 1))}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="5,3 10,7 5,11"/></svg>
            </button>
          </Tip>

          <span className="dv-sep" />

          <div className="dv-zoom">
            <Tip label={t('pdf.zoomOut')}>
              <button onClick={() => bumpZoom(-0.1)}>−</button>
            </Tip>
            <span className="lvl">{Math.round(effZoom * 100)}%</span>
            <Tip label={t('pdf.zoomIn')}>
              <button onClick={() => bumpZoom(+0.1)}>+</button>
            </Tip>
          </div>
          <Tip label={fit ? t('pdf.fitToWidth.on') : t('pdf.fitToWidth')}>
            <button
              className={'dv-btn' + (!fit ? ' on' : '')}
              onClick={() => { if (fit) { setZoom(fitZoom); setFit(false) } else { setFit(true) } }}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                <rect x="2" y="3" width="10" height="8" rx="1"/>
                <polyline points="4.5,6 3,7.5 4.5,9"/>
                <polyline points="9.5,6 11,7.5 9.5,9"/>
                <line x1="3" y1="7.5" x2="11" y2="7.5"/>
              </svg>
            </button>
          </Tip>

          <span className="dv-sep" />

          <Tip label={t('pdf.rotateLeft')}>
            <button className="dv-btn" onClick={() => rotate(-1)}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 7a4 4 0 1 1 1.2 2.85"/>
                <polyline points="3,4 3,7 6,7"/>
              </svg>
            </button>
          </Tip>
          <Tip label={t('pdf.rotateRight')}>
            <button className="dv-btn" onClick={() => rotate(+1)}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M11 7a4 4 0 1 0 -1.2 2.85"/>
                <polyline points="11,4 11,7 8,7"/>
              </svg>
            </button>
          </Tip>

          <span className="dv-sep" />

          <Tip
            label={
              translateBtnState === 'loading'
                ? t('pdf.translate.loading')
                : translateBtnState === 'error' && translateBtnError
                  ? t('pdf.translate.title.failed', { error: translateBtnError })
                  : translateMode === 'cover'
                    ? t('pdf.translate.title.on')
                    : t('pdf.translate.title')
            }
          >
            <button
              className={
                'dv-btn translate-btn'
                + (translateMode === 'cover' ? ' on is-cover' : '')
                + (translateBtnState === 'loading' ? ' is-loading' : '')
                + (translateBtnState === 'error' ? ' is-error' : '')
              }
              aria-pressed={translateMode !== 'off'}
              aria-busy={translateBtnState === 'loading'}
              onClick={() => { if (translateBtnState !== 'loading') onToggleTranslate() }}
            >
              {translateBtnState === 'loading' ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" className="translate-spin">
                  <path d="M7 1.5 a5.5 5.5 0 1 1 -5.5 5.5" />
                </svg>
              ) : (
                <Languages size={14} aria-hidden="true" />
              )}
            </button>
          </Tip>
        </div>
      </TooltipPrimitive.Provider>

      <div className="dv-viewport" ref={viewportRef}>
        <div className="dv-stack">
          {Array.from({ length: pageCount }, (_, i) => i + 1).map(p => (
            <div
              key={p}
              data-page={p}
              ref={el => { pageRefs.current[p] = el }}
              className="dv-sizer"
              style={sizerStyle()}
            >
              <div
                className={'dv-pagewrap' + (isRot ? ' is-rot' : '')}
                style={wrapXform()}
              >
                <div className="pgnum">page {p} / {pageCount}</div>
                {loadedPages.has(p) ? (
                  <>
                    <img
                      src={pdfPageUrl(activeProjectId, activeFilename, p)}
                      alt={`page ${p}`}
                      onLoad={p === 1 ? (e) => {
                        const img = e.target as HTMLImageElement
                        if (img.naturalWidth > 0) setAspectRatio(img.naturalHeight / img.naturalWidth)
                      } : undefined}
                    />
                    <PageOverlays
                      projectId={activeProjectId}
                      filename={activeFilename}
                      page={p}
                      onSpanHover={(idx, el) => openPopoverSoon(p, idx, el)}
                      onSpanLeave={() => scheduleClose()}
                    />
                  </>
                ) : (
                  <div className="dv-placeholder" />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {popover && popoverLine && (
        <TranslatePopover
          anchor={popover.anchor}
          line={popoverLine}
          onClose={onPopoverClose}
          onMouseEnter={onPopoverMouseEnter}
          onMouseLeave={onPopoverMouseLeave}
        />
      )}

      {/* Source-grounding hint — anchored to the doc pane (.rev-pdf is
          position:relative), bottom-center so it never collides with the
          wrapping toolbar. Tells the reviewer to stop hunting: the value
          carries no locatable source in this document. */}
      {locateHint && (
        <div className={'dv-locate-hint' + (locateHint === 'resolving' ? ' is-resolving' : '')} role="status">
          {locateHint === 'resolving' ? (
            <>
              <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="translate-spin" aria-hidden="true">
                <path d="M7 1.5 a5.5 5.5 0 1 1 -5.5 5.5" />
              </svg>
              <span>{t('review.locate.resolving')}</span>
            </>
          ) : (
            <>
              <MapPinOff size={13} strokeWidth={1.7} aria-hidden="true" />
              <span>{t('review.locate.notFound')}</span>
            </>
          )}
        </div>
      )}
    </>
  )
}

// Per-page overlay host. Owns three layers stacked on top of the raster:
//
//   z=1  Selectable text layer — spans come from EITHER the textlayer
//        sidecar (electronic PDFs) OR are derived from translate.lines
//        (vision / scanned mode). pointer-events:auto so the user can
//        rubberband-select original text (HIGH-FREQUENCY action — what
//        reviewers paste into entity fields).
//
//   z=2  Translate ghost — inline translated text painted on top of the
//        raster, low-alpha grey, pointer-events:none. Decorative
//        navigator only; never captures selection or hover. Rendered
//        only when translate state is ready for this page.
//
// Index alignment invariant: text-layer span `i` ↔ translate.lines[i]
// 1-to-1. Two paths preserve this:
//   - textlayer-mode: backend translate.py iterates sidecar spans by
//     enumerate(); indices line up positionally.
//   - vision-mode: text-layer spans are LITERALLY translate.lines, so
//     i is the same array index.
// Hover therefore looks up the popover content by index alone.
function PageOverlays({
  projectId,
  filename,
  page,
  onSpanHover,
  onSpanLeave,
}: {
  projectId: string
  filename: string
  page: number
  onSpanHover: (idx: number, el: HTMLElement) => void
  onSpanLeave: (idx: number) => void
}) {
  const key = `${projectId}::${filename}::${page}`
  const textlayerEnsure = useTextlayer((s) => s.ensure)
  const textlayerState = useTextlayer((s) => s.byKey[key])
  const translateMode = useTranslate((s) => s.mode)
  const translateEnsure = useTranslate((s) => s.ensure)
  const translateState = useTranslate((s) => s.byKey[key])
  // Source-grounding (locate) — rects for the focused field. Keyed by
  // (filename, tabKey); the active tab key drives which cache slice we read.
  const locateTabKey = useReview((s) => s.activeTabKey)
  const focusedPath = useLocate((s) => s.focusedPath)
  const focusedEntity = useLocate((s) => s.focusedEntity)
  const locations = useLocate((s) => s.byKey[`${filename}::${locateTabKey}`])

  // Always fetch textlayer (cheap, makes electronic PDFs selectable
  // without the user toggling anything).
  useEffect(() => {
    textlayerEnsure(projectId, filename, page)
  }, [textlayerEnsure, projectId, filename, page])

  // Fetch translate whenever the global mode is anything but `off`. Both
  // `subtle` and `cover` need the same data; only the ghost layer's CSS
  // changes between them, so we don't refetch on subtle↔cover.
  useEffect(() => {
    if (translateMode === 'off') return
    translateEnsure(projectId, filename, page)
  }, [translateMode, translateEnsure, projectId, filename, page])

  // Choose the spans source. Prefer real sidecar (only available for
  // electronic PDFs) when non-empty; otherwise, if translation has
  // resolved for this page, synthesise a text layer from translate.lines
  // so that PNG / scanned pages also become selectable & copyable.
  const sourceSpans: { spans: SelectableSpan[]; pageW: number; pageH: number } | null = useMemo(() => {
    if (textlayerState?.kind === 'ready' && textlayerState.payload.spans.length > 0) {
      return {
        spans: textlayerState.payload.spans,
        pageW: textlayerState.payload.page_w,
        pageH: textlayerState.payload.page_h,
      }
    }
    if (translateState?.kind === 'ready' && translateState.payload.lines.length > 0) {
      // Derived from translate.lines. font_size default = 12pt; the cqh
      // math in TextLayer scales it relative to the page so the
      // transparent selection rectangle is reasonable.
      return {
        spans: translateState.payload.lines.map((l) => ({
          bbox: l.bbox,
          text: l.original,
          font_size: 12,
        })),
        pageW: translateState.payload.page_w,
        pageH: translateState.payload.page_h,
      }
    }
    return null
  }, [textlayerState, translateState])

  // Page dimensions in PDF points for the locate highlight. Available from the
  // textlayer payload even on scanned pages (empty spans but real page_w/h);
  // fall back to the chosen spans source for vision-only pages.
  const pageDims = useMemo(() => {
    if (textlayerState?.kind === 'ready') {
      return { pageW: textlayerState.payload.page_w, pageH: textlayerState.payload.page_h }
    }
    if (sourceSpans) return { pageW: sourceSpans.pageW, pageH: sourceSpans.pageH }
    return null
  }, [textlayerState, sourceSpans])

  // Only enable hover when translation is loaded for this page —
  // otherwise the popover would surface an empty/missing line.
  const translateReady = translateMode !== 'off' && translateState?.kind === 'ready'
  const hoverHook = translateReady ? onSpanHover : undefined
  const leaveHook = translateReady ? onSpanLeave : undefined

  return (
    <>
      {/* Source-grounding highlight: above the raster <img>, below the
          selectable text layer (rendered first → lower in DOM stacking). */}
      {pageDims && locations && locations.length > 0 && (
        <LocateHighlight
          locations={locations}
          focusedPath={focusedPath}
          focusedEntity={focusedEntity}
          page={page}
          pageW={pageDims.pageW}
          pageH={pageDims.pageH}
        />
      )}
      {sourceSpans && (
        <TextLayer
          spans={sourceSpans.spans}
          pageW={sourceSpans.pageW}
          pageH={sourceSpans.pageH}
          onSpanHover={hoverHook}
          onSpanLeave={leaveHook}
        />
      )}
      {translateReady && (
        <TranslateGhost
          lines={translateState!.payload.lines}
          pageW={translateState!.payload.page_w}
          pageH={translateState!.payload.page_h}
        />
      )}
    </>
  )
}
