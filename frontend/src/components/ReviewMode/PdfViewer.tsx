import { useEffect, useRef, useState } from 'react'
import { Languages } from 'lucide-react'
import { pdfPageUrl } from '../../lib/api'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'
import { useTextlayer } from '../../stores/textlayer'
import { useTranslate } from '../../stores/translate'
import TextLayer from './TextLayer'
import TranslateOverlay from './TranslateOverlay'

export default function PdfViewer() {
  const { activeProjectId, activeFilename, page, pageCount, setPageCount } = useReview()
  const { byProject } = useDocs()
  // Translate mode is driven by both the toolbar button and the `T` key
  // — subscribe so the button reflects state changes from either path.
  const translateMode = useTranslate((s) => s.mode)
  const translateByKey = useTranslate((s) => s.byKey)

  const [visiblePage, setVisiblePage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [rot, setRot] = useState(0) // 0 | 90 | 180 | 270
  const [fit, setFit] = useState(true)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set([1]))
  const [vpW, setVpW] = useState(600)
  const [aspectRatio, setAspectRatio] = useState(11 / 8.5)

  const viewportRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})

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
    pageRefs.current = {}
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

  // Scroll → update visible page indicator
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
    }
    vp.addEventListener('scroll', onScroll, { passive: true })
    return () => vp.removeEventListener('scroll', onScroll)
  }, [pageCount])

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
  if (translateMode === 'on' && docKeyPrefix) {
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

  function onToggleTranslate() {
    if (!activeProjectId || !activeFilename) return
    const next: 'on' | 'off' = useTranslate.getState().mode === 'on' ? 'off' : 'on'
    useTranslate.getState().setMode(next)
    if (next === 'on') {
      // Fan-out: trigger ensure() for every currently-loaded page. New
      // pages scrolled into view after this will trigger via the per-page
      // host component below.
      const ensure = useTranslate.getState().ensure
      for (const p of loadedPages) {
        ensure(activeProjectId, activeFilename, p)
      }
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
        if (st.mode !== 'on') st.setMode('on')
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

  if (!activeProjectId || !activeFilename) return null

  return (
    <>
      <div className="dv-toolbar">
        <button className="dv-btn" title="previous page"
          disabled={visiblePage <= 1 || pageCount <= 1}
          onClick={() => jumpToPage(Math.max(1, visiblePage - 1))}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="9,3 4,7 9,11"/></svg>
        </button>
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
        <button className="dv-btn" title="next page"
          disabled={visiblePage >= pageCount || pageCount <= 1}
          onClick={() => jumpToPage(Math.min(pageCount, visiblePage + 1))}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"><polyline points="5,3 10,7 5,11"/></svg>
        </button>

        <span className="dv-sep" />

        <div className="dv-zoom">
          <button onClick={() => bumpZoom(-0.1)} title="zoom out">−</button>
          <span className="lvl">{Math.round(effZoom * 100)}%</span>
          <button onClick={() => bumpZoom(+0.1)} title="zoom in">+</button>
        </div>
        <button
          className={'dv-btn' + (!fit ? ' on' : '')}
          title={fit ? 'fit to width (on)' : 'fit to width'}
          onClick={() => { if (fit) { setZoom(fitZoom); setFit(false) } else { setFit(true) } }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="3" width="10" height="8" rx="1"/>
            <polyline points="4.5,6 3,7.5 4.5,9"/>
            <polyline points="9.5,6 11,7.5 9.5,9"/>
            <line x1="3" y1="7.5" x2="11" y2="7.5"/>
          </svg>
        </button>

        <span className="dv-sep" />

        <button className="dv-btn" title="rotate left 90°" onClick={() => rotate(-1)}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 7a4 4 0 1 1 1.2 2.85"/>
            <polyline points="3,4 3,7 6,7"/>
          </svg>
        </button>
        <button className="dv-btn" title="rotate right 90°" onClick={() => rotate(+1)}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M11 7a4 4 0 1 0 -1.2 2.85"/>
            <polyline points="11,4 11,7 8,7"/>
          </svg>
        </button>

        <span className="dv-sep" />

        <button
          className={
            'dv-btn translate-btn'
            + (translateMode === 'on' ? ' on' : '')
            + (translateBtnState === 'loading' ? ' is-loading' : '')
            + (translateBtnState === 'error' ? ' is-error' : '')
          }
          title={
            translateBtnState === 'error' && translateBtnError
              ? `翻译失败: ${translateBtnError} (T)`
              : translateMode === 'on'
                ? '关闭翻译 (T) · Shift+T 重译本页'
                : '翻译此 doc (T)'
          }
          aria-pressed={translateMode === 'on'}
          onClick={onToggleTranslate}
        >
          {translateBtnState === 'loading' ? (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" className="translate-spin">
              <path d="M7 1.5 a5.5 5.5 0 1 1 -5.5 5.5" />
            </svg>
          ) : (
            <Languages size={14} aria-hidden="true" />
          )}
        </button>
      </div>

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
                    <TextLayerHost projectId={activeProjectId} filename={activeFilename} page={p} />
                    <TranslateOverlayHost projectId={activeProjectId} filename={activeFilename} page={p} />
                  </>
                ) : (
                  <div className="dv-placeholder" />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

// Thin per-page wrapper: fires `ensure(...)` on mount / page change and
// renders the transparent <TextLayer/> once the payload arrives. Scanned
// pages resolve with `spans: []` → renders nothing. Errors are silent —
// selection is a "nice to have" and not worth surfacing chrome for.
function TextLayerHost({
  projectId,
  filename,
  page,
}: {
  projectId: string
  filename: string
  page: number
}) {
  const key = `${projectId}::${filename}::${page}`
  const ensure = useTextlayer((s) => s.ensure)
  const state = useTextlayer((s) => s.byKey[key])

  useEffect(() => {
    ensure(projectId, filename, page)
  }, [ensure, projectId, filename, page])

  if (!state || state.kind !== 'ready') return null
  const { payload } = state
  return <TextLayer spans={payload.spans} pageW={payload.page_w} pageH={payload.page_h} />
}

// Per-page translate host. Subscribes to the global `mode` flag + this
// page's cache entry. The store's `ensure(...)` is a no-op when mode is
// 'off', so the only side-effect of calling it eagerly here is the
// initial fetch once the user flips the toolbar on (and on doc / page
// change while already on). Loading / error states render nothing on
// the page itself — the toolbar button is the single source of truth
// for global progress.
function TranslateOverlayHost({
  projectId,
  filename,
  page,
}: {
  projectId: string
  filename: string
  page: number
}) {
  const key = `${projectId}::${filename}::${page}`
  const mode = useTranslate((s) => s.mode)
  const ensure = useTranslate((s) => s.ensure)
  const state = useTranslate((s) => s.byKey[key])

  useEffect(() => {
    if (mode !== 'on') return
    ensure(projectId, filename, page)
  }, [mode, ensure, projectId, filename, page])

  if (mode !== 'on' || !state || state.kind !== 'ready') return null
  const { payload } = state
  return <TranslateOverlay lines={payload.lines} pageW={payload.page_w} pageH={payload.page_h} />
}
