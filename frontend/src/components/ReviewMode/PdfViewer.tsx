import { useEffect, useRef, useState } from 'react'
import { pdfPageUrl } from '../../lib/api'
import { useDocs } from '../../stores/docs'
import { useReview } from '../../stores/review'

export default function PdfViewer() {
  const { activeProjectId, activeDocId, page, pageCount, setPageCount } = useReview()
  const { byProject } = useDocs()

  const [visiblePage, setVisiblePage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [rot, setRot] = useState(0) // 0 | 90 | 180 | 270
  const [fit, setFit] = useState(true)
  const [loadedPages, setLoadedPages] = useState<Set<number>>(new Set([1]))
  const [vpW, setVpW] = useState(600)
  const [aspectRatio, setAspectRatio] = useState(11 / 8.5)

  const viewportRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})

  // Sync pageCount from doc store
  useEffect(() => {
    if (!activeProjectId || !activeDocId) return
    const doc = byProject[activeProjectId]?.find(d => d.doc_id === activeDocId)
    if (doc?.page_count) setPageCount(doc.page_count)
  }, [activeProjectId, activeDocId, byProject, setPageCount])

  // Reset on doc change
  useEffect(() => {
    setVisiblePage(1)
    setZoom(1)
    setRot(0)
    setFit(true)
    setLoadedPages(new Set([1]))
    setAspectRatio(11 / 8.5)
    pageRefs.current = {}
  }, [activeDocId])

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
  }, [activeDocId])

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
  }, [pageCount, activeDocId])

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

  if (!activeProjectId || !activeDocId) return null

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
                  <img
                    src={pdfPageUrl(activeProjectId, activeDocId, p)}
                    alt={`page ${p}`}
                    onLoad={p === 1 ? (e) => {
                      const img = e.target as HTMLImageElement
                      if (img.naturalWidth > 0) setAspectRatio(img.naturalHeight / img.naturalWidth)
                    } : undefined}
                  />
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
