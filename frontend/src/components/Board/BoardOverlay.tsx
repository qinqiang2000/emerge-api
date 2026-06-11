// BoardOverlay — the audit board (`?board=1`), an excalidraw canvas with the
// latest audit report's group docs laid out as columns and every located
// evidence quote circled in place.
//
// Lifecycle mirrors `BenchOverlay` exactly:
//   - App.tsx mounts this component when `?board=1` is in the URL search
//     string AND a project is selected; presence of the param IS the open
//     state. `onClose` lets App.tsx strip the param.
//   - ESC, the close button, the backdrop click and a project switch all
//     funnel into `onClose`.
//   - The whole `components/Board/` dir is one React.lazy chunk — excalidraw
//     (+200 packages) never enters the main bundle.
//
// Two-way linkage (proven in the spike):
//   rail row click → `scrollToContent` on that check's elements + swap the
//     single `ring-focus` element (focus WITHOUT selection — selecting would
//     float excalidraw's property-panel island over the canvas, trap #2);
//   canvas click on an `ev-*` / `arrow-*` element → activate the rail row via
//     `onChange`'s selectedElementIds.
//
// User-drawn elements (any id outside our namespaces) are the user's notes —
// persisted through `useBoard.saveNotes` (1s debounce) and restored on the
// next open. Red line: rects live only here, in the render layer.

import './boardAssets' // MUST stay the first import — sets EXCALIDRAW_ASSET_PATH
import { Excalidraw, convertToExcalidrawElements } from '@excalidraw/excalidraw'
import '@excalidraw/excalidraw/index.css'
import type { BinaryFileData, ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types'
import { X } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useT } from '../../i18n'
import { pdfPageUrl } from '../../lib/api'
import { evKey, useBoard } from '../../stores/board'
import { useDocs } from '../../stores/docs'
import { useProjects } from '../../stores/projects'
import { STATUS_GLYPH } from '../Chat/AuditCard'
import {
  OWN_ID_RE,
  RING_ID,
  arrowId,
  buildCheckOverlays,
  buildPageSkeletons,
  checkIdxOfElementId,
  imgId,
  layoutPages,
  pullPagesFront,
  readBoardColors,
  type BoardDocInput,
  type CheckStatus,
  type EvidenceOnBoard,
  type LaidPage,
} from './boardScene'

type SceneElement = ReturnType<ExcalidrawImperativeAPI['getSceneElements']>[number]

/** Page-image elements geometrically under the given overlay elements (an
 *  ellipse sits inside its page) — used to widen a zoom target from bare
 *  circles to readable page context. */
function pagesUnder(api: ExcalidrawImperativeAPI, overlays: SceneElement[]): SceneElement[] {
  const images = api.getSceneElements().filter(e => e.id.startsWith('img-'))
  const out: SceneElement[] = []
  for (const o of overlays) {
    const cx = o.x + o.width / 2
    const cy = o.y + o.height / 2
    const host = images.find(im =>
      cx >= im.x && cx <= im.x + im.width && cy >= im.y && cy <= im.y + im.height)
    if (host && !out.includes(host)) out.push(host)
  }
  return out
}

interface Props {
  slug: string
  onClose: () => void
  /** Same contract as BenchOverlay#hidden: keep the React tree mounted (scene
   *  + caches survive) but yank it out of layout/event flow and stand down
   *  the Esc listener while a higher overlay owns the keyboard. */
  hidden?: boolean
}

/** Fetch one page raster → dataURL + natural dims. Best-effort: a missing /
 *  failed page resolves to null and the board simply lays out without it. */
async function loadPageImage(
  slug: string,
  filename: string,
  page: number,
): Promise<{ dataURL: string; mimeType: string; w: number; h: number } | null> {
  try {
    const resp = await fetch(pdfPageUrl(slug, filename, page))
    if (!resp.ok) return null
    const blob = await resp.blob()
    const dataURL = await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(r.result as string)
      r.onerror = () => reject(new Error('read failed'))
      r.readAsDataURL(blob)
    })
    const dims = await new Promise<{ w: number; h: number }>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight })
      img.onerror = () => reject(new Error('decode failed'))
      img.src = dataURL
    })
    return { dataURL, mimeType: blob.type || 'image/png', ...dims }
  } catch {
    return null
  }
}

export default function BoardOverlay({ slug, onClose, hidden = false }: Props) {
  const entry = useBoard(s => s.byProject[slug])
  const loading = useBoard(s => !!s.loading[slug])
  const error = useBoard(s => s.errors[slug])
  const notes = useBoard(s => s.notesByProject[slug])
  const load = useBoard(s => s.load)
  const loadNotes = useBoard(s => s.loadNotes)
  const t = useT()

  const [api, setApi] = useState<ExcalidrawImperativeAPI | null>(null)
  // Ops-first: the board's imperative surface is addressable from the console
  // / agent drivers, mirroring how kbd + tools share one op layer.
  useEffect(() => {
    ;(window as unknown as Record<string, unknown>).__emergeBoardApi = api ?? undefined
    return () => { (window as unknown as Record<string, unknown>).__emergeBoardApi = undefined }
  }, [api])
  const [activeCheck, setActiveCheck] = useState<number | null>(null)
  const [sceneReady, setSceneReady] = useState(false)
  // "docs list refresh attempted" — the scene build needs page counts but must
  // not stall forever if the docs fetch fails (fallback: max evidence page).
  const [docsReady, setDocsReady] = useState<boolean>(() => !!useDocs.getState().byProject[slug])
  const builtFor = useRef<string | null>(null)
  const fittedFor = useRef<string | null>(null)
  const mountedRef = useRef(true)
  /** Scene inputs kept for on-demand per-check overlay mounts + the
   *  cited-docs-adjacent relayout (focusCheck). */
  const sceneDataRef = useRef<{
    checks: { status: CheckStatus }[]
    evidences: EvidenceOnBoard[]
    laid: Map<string, LaidPage>
    docs: BoardDocInput[]
  } | null>(null)
  const notesRestoredFor = useRef<string | null>(null)
  const lastNoteSig = useRef('')

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  // Resolved once per mount — the board lives inside the themed DOM, so the
  // semantic tokens (--moss/--rose/--ochre/...) are available by now.
  const colors = useMemo(() => readBoardColors(), [])

  // Cache-first loads. The store dedupes concurrent loads per slug.
  useEffect(() => {
    void load(slug)
    void loadNotes(slug)
    void useDocs.getState().refresh(slug).then(() => setDocsReady(true))
  }, [slug, load, loadNotes])

  // ESC closes — window-level listener, stood down while hidden (same
  // conventions as BenchOverlay).
  useEffect(() => {
    if (hidden) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, hidden])

  // Project switch → auto-close (mirrors BenchOverlay / PromptQuickLook).
  useEffect(() => {
    const unsub = useProjects.subscribe(s => {
      if (s.selectedSlug !== null && s.selectedSlug !== slug) {
        onClose()
      }
    })
    return unsub
  }, [slug, onClose])

  // ── Scene build ──────────────────────────────────────────────────────────
  // Once per (slug, run): measure every group doc's page rasters, register
  // them as excalidraw files, lay out the columns and draw the evidence
  // overlays. `regenerateIds: false` is load-bearing (trap #1) — the rail ↔
  // canvas linkage keys on our deterministic ids.
  useEffect(() => {
    if (!api || !entry?.report || !docsReady) return
    const report = entry.report
    const buildKey = `${slug}:${report.run_id}`
    if (builtFor.current === buildKey) return
    let cancelled = false

    async function build() {
      const docSummaries = useDocs.getState().byProject[slug] ?? []
      const docInputs: BoardDocInput[] = []
      const files: BinaryFileData[] = []
      for (const fn of Object.keys(report.group)) {
        const summary = docSummaries.find(d => d.filename === fn)
        // Page count: docs sidecar wins; fall back to the largest page number
        // any evidence (hint or locate result) mentions for this doc.
        let pageCount = summary?.page_count ?? 0
        if (!pageCount) {
          let maxPage = 1
          report.checks.forEach((c, i) => {
            (c.evidence ?? []).forEach((e, j) => {
              if (e.doc !== fn) return
              const loc = entry.locations[evKey(i, j)]
              maxPage = Math.max(maxPage, loc?.page ?? 0, e.page ?? 0)
            })
          })
          pageCount = maxPage
        }
        const ext = summary?.ext ?? (fn.includes('.') ? fn.split('.').pop()! : '')
        const pages: BoardDocInput['pages'] = []
        for (let p = 1; p <= pageCount; p++) {
          const img = await loadPageImage(slug, fn, p)
          if (cancelled) return
          if (!img) continue
          pages.push({ page: p, w: img.w, h: img.h })
          files.push({
            id: imgId(fn, p) as BinaryFileData['id'],
            dataURL: img.dataURL as BinaryFileData['dataURL'],
            mimeType: img.mimeType as BinaryFileData['mimeType'],
            created: Date.now(),
          })
        }
        if (pages.length) docInputs.push({ name: fn, ext, pages })
      }
      if (cancelled || !api) return

      // Few-paged docs first (anchor 报价单/订单/收货单-shaped docs cluster
      // left, a 18-page appendix goes right) — cross-doc checks then zoom to
      // ADJACENT pages instead of spanning the whole board (dogfood
      // 2026-06-11). Content-agnostic: page count only, no doc-type smarts.
      docInputs.sort((a, b) => a.pages.length - b.pages.length)

      api.addFiles(files)
      const laid = layoutPages(docInputs)
      const evidences: EvidenceOnBoard[] = []
      report.checks.forEach((c, i) => {
        (c.evidence ?? []).forEach((e, j) => {
          const loc = entry.locations[evKey(i, j)]
          evidences.push({
            checkIdx: i,
            evIdx: j,
            doc: e.doc,
            page: loc?.page ?? e.page ?? null,
            rects: loc?.rects ?? [],
            status: loc?.status ?? 'none',
          })
        })
      })
      sceneDataRef.current = { checks: report.checks, evidences, laid, docs: docInputs }
      // Pages only — per-check circles/arrows mount on demand via
      // applyCheck (user 2026-06-11: all checks at once = 一板的线, 乱).
      const skeletons = buildPageSkeletons([...laid.values()], colors)
      api.updateScene({
        // trap #1 — regenerateIds defaults to true and would sever every
        // rail↔element linkage.
        elements: convertToExcalidrawElements(skeletons as never, { regenerateIds: false }),
      })
      builtFor.current = buildKey
      // Fit the viewport one tick after excalidraw commits the elements (the
      // post-update tick the spike needed) — but do NOT ride this effect's
      // `cancelled` flag: `entry`'s store ref churns right after the build
      // (notes/loading updates), the re-run cleanup cancelled the pending fit
      // and the builtFor guard skipped re-fitting → viewport stranded at 100%
      // on empty (0,0), reading as a blank board (prod dogfood 2026-06-11).
      // The committed scene survives those re-runs; the fit must too.
      const fitApi = api
      // Initial view answers "定位": land on the FIRST check that has located
      // evidence (its circles mounted + zoomed) instead of fitting the whole
      // board — a 20+-page group fits at ~10% zoom, which reads as unusable.
      const firstIdx = report.checks.findIndex((_, i) =>
        evidences.some(e => e.checkIdx === i && e.rects.length > 0))
      setTimeout(() => {
        if (!mountedRef.current || fittedFor.current === buildKey || !fitApi) return
        fittedFor.current = buildKey
        if (firstIdx >= 0) {
          applyCheckRef.current?.(firstIdx)
        } else {
          fitApi.scrollToContent(undefined, { fitToViewport: true })
        }
      }, 100)
      setSceneReady(true)
    }

    void build()
    return () => { cancelled = true }
  }, [api, entry, docsReady, slug, colors])

  // ── Notes restore ────────────────────────────────────────────────────────
  // Saved elements are full excalidraw elements — append them once per run
  // after the skeleton scene exists. Seeding `lastNoteSig` prevents the
  // restore itself from echoing straight back into saveNotes.
  useEffect(() => {
    if (!api || !sceneReady || !entry?.report || notes === undefined) return
    const key = `${slug}:${entry.report.run_id}`
    if (notesRestoredFor.current === key) return
    notesRestoredFor.current = key
    const els = (notes?.elements ?? []) as SceneElement[]
    if (!els.length) return
    const current = api.getSceneElements()
    const have = new Set(current.map(e => e.id))
    const restored = els.filter(e => e && typeof e.id === 'string' && !have.has(e.id))
    if (!restored.length) return
    lastNoteSig.current = restored
      .map(e => `${e.id}:${(e as { version?: number }).version ?? 0}`)
      .join('|')
    api.updateScene({ elements: [...current, ...restored] })
  }, [api, sceneReady, entry, notes, slug])

  // ── Rail → canvas ────────────────────────────────────────────────────────
  // Mount ONLY the active check's circles/arrow/badges, then zoom to them.
  // All checks at once read as "一板的线，乱" (user 2026-06-11) — the rail is
  // the index, the canvas shows one check's story at a time. The ochre focus
  // ring became redundant with single-check display and was dropped.
  const focusCheck = useCallback((idx: number) => {
    setActiveCheck(idx)
    if (!api || !sceneDataRef.current) return
    const { checks, evidences, docs } = sceneDataRef.current
    let { laid } = sceneDataRef.current

    // Cited docs snap ADJACENT (user 2026-06-11: 报价单↔收货单 with 订单 in
    // between read as odd). Reorder = cited docs first (evidence order),
    // the rest keep their relative order; pages + captions + any user note
    // sitting on a moved page translate by that page's delta.
    const citedDocs: string[] = []
    for (const e of entry?.report?.checks[idx]?.evidence ?? []) {
      if (typeof e?.doc === 'string' && e.doc && !citedDocs.includes(e.doc)) citedDocs.push(e.doc)
    }
    const moveDelta = new Map<string, { dx: number; dy: number }>() // element id → delta
    const oldPages = [...laid.values()]
    if (citedDocs.length >= 2) {
      // Cited PAGES bubble to each doc's leading sub-column — doc adjacency
      // alone leaves a circle deep in an 18-page grid a whole band away from
      // its partner (dogfood 2026-06-11). Few-paged docs sit left, so the
      // big doc's leading column lands right beside them.
      const citedPages = new Map<string, number[]>()
      for (const ev of evidences) {
        if (ev.checkIdx !== idx || !ev.doc || ev.page == null) continue
        const arr = citedPages.get(ev.doc) ?? []
        if (!arr.includes(ev.page)) arr.push(ev.page)
        citedPages.set(ev.doc, arr)
      }
      const ordered = [
        ...citedDocs
          .map(d => docs.find(dd => dd.name === d))
          .filter((d): d is BoardDocInput => !!d)
          .sort((a, b) => a.pages.length - b.pages.length)
          .map(d => pullPagesFront(d, citedPages.get(d.name) ?? [])),
        ...docs.filter(d => !citedDocs.includes(d.name)),
      ]
      const newLaid = layoutPages(ordered)
      for (const [k, np] of newLaid) {
        const op = laid.get(k)
        if (!op) continue
        const dx = np.x - op.x
        const dy = np.y - op.y
        if (dx || dy) {
          moveDelta.set(imgId(np.doc, np.page), { dx, dy })
          moveDelta.set(`lbl-${np.doc}-p${np.page}`, { dx, dy })
        }
      }
      laid = newLaid
      sceneDataRef.current = { ...sceneDataRef.current, laid }
    }
    const deltaFor = (e: SceneElement): { dx: number; dy: number } | undefined => {
      const direct = moveDelta.get(e.id)
      if (direct) return direct
      if (OWN_ID_RE.test(e.id)) return undefined
      // user note: carried by whichever (pre-move) page contains its center
      const cx = e.x + e.width / 2
      const cy = e.y + e.height / 2
      const host = oldPages.find(p =>
        cx >= p.x && cx <= p.x + p.w && cy >= p.y && cy <= p.y + p.h)
      return host ? moveDelta.get(imgId(host.doc, host.page)) : undefined
    }

    const overlays = buildCheckOverlays(
      checks,
      evidences.filter(e => e.checkIdx === idx),
      laid,
      colors,
    )
    const keep = api.getSceneElements()
      .filter(e => {
        if (e.id.startsWith('ev-') || e.id.startsWith('arrow-')
          || e.id.startsWith('badge-') || e.id === RING_ID) return false
        // excalidraw mints a random-id TEXT element for each arrow label and
        // binds it via containerId — drop it with its arrow or it orphans
        const containerId = (e as { containerId?: string | null }).containerId
        return !(containerId && String(containerId).startsWith('arrow-'))
      })
      .map(e => {
        const d = moveDelta.size ? deltaFor(e) : undefined
        return d ? { ...e, x: e.x + d.dx, y: e.y + d.dy, version: e.version + 1 } : e
      })
    api.updateScene({
      elements: [
        ...keep,
        // trap #1 — regenerateIds would sever the rail↔element linkage
        ...convertToExcalidrawElements(overlays as never, { regenerateIds: false }),
      ],
    })
    const prefix = `ev-${idx}-`
    const els = api.getSceneElements().filter(
      e => e.id.startsWith(prefix) || e.id === arrowId(idx),
    )
    if (!els.length) {
      // Unlocated check (e.g. quote missed alignment): a click must still
      // answer — zoom to the cited docs' pages so the reviewer lands on the
      // right document context instead of nothing happening (dogfood
      // 2026-06-11: rules whose quotes all missed read as "click is dead").
      const cited = (entry?.report?.checks[idx]?.evidence ?? [])
        .filter(e => typeof e?.doc === 'string' && e.doc)
        .map(e => imgId(e.doc, e.page ?? 1))
      const pageEls = api.getSceneElements().filter(e => cited.includes(e.id))
      if (pageEls.length) {
        api.scrollToContent(pageEls, { fitToViewport: true, animate: true, viewportZoomFactor: 0.85 })
      }
      return
    }
    // Zoom target = the circles PLUS the page images under them — fitting a
    // bare ellipse lands at 300%+ ("怼脸"), while the page keeps the evidence
    // readable in context (and shows both pages for a cross-doc check).
    const scope = [...els, ...pagesUnder(api, els.filter(e => e.id.startsWith(prefix)))]
    api.scrollToContent(scope, { fitToViewport: true, animate: true, viewportZoomFactor: 0.85 })
  }, [api, colors, entry])

  // Latest focusCheck for the build effect's post-commit timeout (the effect
  // must not depend on the callback identity — see the fit-survival note).
  const applyCheckRef = useRef<typeof focusCheck | null>(null)
  applyCheckRef.current = focusCheck

  // ── Canvas → rail + notes capture ───────────────────────────────────────
  const onChange = useCallback((
    els: readonly SceneElement[],
    appState: { selectedElementIds?: Record<string, boolean> },
  ) => {
    const sel = Object.keys(appState?.selectedElementIds ?? {})
    const hit = sel.map(checkIdxOfElementId).find(v => v !== null)
    if (hit != null) {
      setActiveCheck(prev => (prev === hit ? prev : hit))
    }
    if (!sceneReady || !entry?.report) return
    // User notes = live elements outside our id namespaces that also aren't
    // text bound INTO one of ours (excalidraw mints a random-id label element
    // for each `arrow-*`'s ✓/✗ label — containerId points back at the arrow).
    const user = els.filter(e => {
      if (e.isDeleted) return false
      if (OWN_ID_RE.test(e.id)) return false
      const containerId = (e as { containerId?: string | null }).containerId
      return !(containerId && OWN_ID_RE.test(containerId))
    })
    const sig = user.map(e => `${e.id}:${e.version}`).join('|')
    if (sig !== lastNoteSig.current) {
      lastNoteSig.current = sig
      useBoard.getState().saveNotes(
        slug,
        entry.report.run_id,
        user.map(e => JSON.parse(JSON.stringify(e)) as unknown),
      )
    }
  }, [sceneReady, entry, slug])

  const retry = () => {
    useBoard.getState().invalidate(slug)
    void useBoard.getState().load(slug)
  }

  const staleNotes = !!(
    notes && entry?.report && notes.run_id && notes.run_id !== entry.report.run_id
  )

  return (
    <div
      // Full-bleed (dogfood 2026-06-11): a 20+-page group needs every pixel —
      // no scrim margin, the board IS the screen. ESC / ✕ close; display:none
      // when hidden keeps the scene mounted but cedes layout + keyboard.
      className="fixed inset-0 z-40"
      style={{ display: hidden ? 'none' : undefined }}
      role="dialog"
      aria-label="board"
      aria-modal="true"
      aria-hidden={hidden}
    >
      <div
        className="bg-paper text-ink flex w-full h-full overflow-hidden relative"
        onClick={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          className="absolute top-2 right-2 z-10 p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
          aria-label={t('board.close.aria')}
          title={t('board.close')}
          onClick={onClose}
        >
          <X size={16} />
        </button>

        {error ? (
          <div data-testid="board-error" role="alert" className="m-auto font-mono text-sm text-ink-3 flex items-center gap-2">
            <span>{t('board.error.title')}</span>
            <span>·</span>
            <button type="button" className="text-ochre-2 hover:underline" onClick={retry}>
              {t('board.error.retry')}
            </button>
          </div>
        ) : !entry ? (
          <div data-testid="board-loading" aria-busy={loading} className="m-auto font-mono text-sm text-ink-3">
            {t('board.loading')}
          </div>
        ) : !entry.report ? (
          <div data-testid="board-empty" className="m-auto font-mono text-sm text-ink-3">
            {t('board.empty')}
          </div>
        ) : (
          <>
            {/* Check rail — same row anatomy as AuditCard (glyph + rule +
                quote sub-lines); the card stays text-only, the board adds the
                spatial layer. */}
            <div className="w-[320px] shrink-0 border-r border-rule-soft overflow-y-auto font-mono text-sm">
              <div className="px-3 py-2 border-b border-rule-soft text-ink font-semibold">
                {t('board.checks.title')}
                <span className="ml-2 text-ink-4 text-xs font-normal">
                  {entry.report.checks.filter(c => c.status === 'pass').length}/{entry.report.checks.length}
                </span>
              </div>
              {entry.report.checks.map((c, i) => (
                <div
                  key={i}
                  data-testid={`board-check-${i}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => focusCheck(i)}
                  onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); focusCheck(i) } }}
                  className={`px-3 py-1.5 border-b border-rule-soft cursor-pointer ${
                    activeCheck === i
                      ? 'bg-paper-3 border-l-2 border-l-ochre'
                      : 'border-l-2 border-l-transparent hover:bg-paper-2'
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <span className={`${STATUS_GLYPH[c.status].cls} shrink-0`}>
                      {STATUS_GLYPH[c.status].glyph}
                    </span>
                    <span className="text-ink min-w-0 break-words">{c.rule}</span>
                  </div>
                  {(c.evidence ?? []).map((e, j) => (
                    <div key={j} className="pl-5 text-xs text-ink-4 break-words">
                      「{e.quote}」 — {e.doc}
                      {e.page != null ? ` · p${e.page}` : ''}
                    </div>
                  ))}
                </div>
              ))}
              {staleNotes && (
                <div className="px-3 py-2 text-xs text-ink-4">{t('board.notes.stale')}</div>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <Excalidraw
                excalidrawAPI={setApi}
                onChange={onChange}
                initialData={{ appState: { viewBackgroundColor: colors.canvas } }}
                UIOptions={{
                  // Trim the chrome to what the board needs: pan/zoom + the
                  // drawing tools stay (user notes are a feature); scene-level
                  // file actions (load/save/export/clear/theme) are off — the
                  // scene is derived from the report, notes persist via
                  // board_notes.
                  canvasActions: {
                    changeViewBackgroundColor: false,
                    clearCanvas: false,
                    export: false,
                    loadScene: false,
                    saveToActiveFile: false,
                    toggleTheme: false,
                    saveAsImage: false,
                  },
                  tools: { image: false },
                }}
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
