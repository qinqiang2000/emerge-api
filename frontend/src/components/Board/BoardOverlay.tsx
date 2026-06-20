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
import { PanelLeftClose, PanelLeftOpen, Pencil, X } from 'lucide-react'
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
  annotateUserElements,
  arrowId,
  buildCheckOverlays,
  buildPagePlaceholders,
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

// Check rail sizing — same drag/collapse/persist vocabulary as Shell.tsx, but
// the board owns its own flex layout (fixed inset-0), so we can't reuse Shell.
// Expanded: drag the right edge to resize (clamped, persisted). Collapsed: a
// narrow numbered rail (1-based, status-colored) that still focuses checks —
// the numbers match the canvas's unlocated-evidence badges.
const RAIL_W_KEY = 'emerge.boardRailW'
const RAIL_COLLAPSED_KEY = 'emerge.boardRailCollapsed'
const RAIL_DEFAULT = 320
const RAIL_MIN = 240
const RAIL_MAX = 560
const RAIL_MINI_W = 48

function readStoredRailW(): number {
  try {
    const v = localStorage.getItem(RAIL_W_KEY)
    if (v !== null) {
      const n = parseInt(v, 10)
      if (!isNaN(n)) return Math.max(RAIL_MIN, Math.min(RAIL_MAX, n))
    }
  } catch { /* ignore */ }
  return RAIL_DEFAULT
}

function readStoredRailCollapsed(): boolean {
  try { return localStorage.getItem(RAIL_COLLAPSED_KEY) === '1' } catch { return false }
}

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

/** Fetch one page raster → dataURL. Dims come from `page_sizes` now, so this
 *  no longer decodes for natural size — it just downloads + base64s, and each
 *  page streams into the canvas the instant it lands (no whole-group barrier).
 *  Best-effort: a missing / failed page resolves to null and that page keeps
 *  its placeholder box. */
async function loadPageImage(
  slug: string,
  filename: string,
  page: number,
): Promise<{ dataURL: string; mimeType: string } | null> {
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
    return { dataURL, mimeType: blob.type || 'image/png' }
  } catch {
    return null
  }
}

// A4 portrait @150dpi (8.27×11.69in) — the placeholder page box for a doc
// whose sidecar predates `page_sizes` (compute failure; existing docs are
// backfilled by list_docs). The raster scales into this box on arrival.
const A4_FALLBACK = { w: 1240, h: 1754 }

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
  // Annotate mode — the board opens read-first: `viewModeEnabled` hides
  // excalidraw's whole tool palette (the chrome that's in the way when you're
  // only reading), while pan/zoom and previously-drawn notes still render. The
  // reviewer flips this on to mark up; entering auto-picks the pen so the shape
  // palette never has to be touched (a board note = a freedraw circle, the B5
  // teaching signal). Transient by design — every open starts clean, unlike
  // rail collapse which persists.
  const [annotating, setAnnotating] = useState(false)
  const toggleAnnotate = useCallback(() => setAnnotating(v => !v), [])
  useEffect(() => {
    if (annotating) api?.setActiveTool({ type: 'freedraw' })
  }, [annotating, api])
  // Rail sizing — drag the right edge to resize, collapse to a numbered mini
  // rail. Both persist (mirrors Shell.tsx). The drag listener mounts only
  // while dragging.
  const [railW, setRailWState] = useState<number>(() => readStoredRailW())
  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => readStoredRailCollapsed())
  const [railDrag, setRailDrag] = useState<boolean>(false)
  const railDragStartX = useRef<number>(0)
  const railDragStartW = useRef<number>(0)

  const setRailW = useCallback((w: number) => {
    const clamped = Math.max(RAIL_MIN, Math.min(RAIL_MAX, w))
    setRailWState(clamped)
    try { localStorage.setItem(RAIL_W_KEY, String(clamped)) } catch { /* ignore */ }
  }, [])

  const toggleRail = useCallback(() => {
    setRailCollapsed(prev => {
      const next = !prev
      try { localStorage.setItem(RAIL_COLLAPSED_KEY, next ? '1' : '0') } catch { /* ignore */ }
      return next
    })
  }, [])

  useEffect(() => {
    if (!railDrag) return
    function onMove(clientX: number) {
      setRailW(railDragStartW.current + (clientX - railDragStartX.current))
    }
    function handleMouseMove(e: MouseEvent) { onMove(e.clientX) }
    function handleTouchMove(e: TouchEvent) { if (e.touches.length > 0) onMove(e.touches[0].clientX) }
    function handleEnd() { setRailDrag(false) }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleEnd)
    window.addEventListener('touchmove', handleTouchMove)
    window.addEventListener('touchend', handleEnd)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleEnd)
      window.removeEventListener('touchmove', handleTouchMove)
      window.removeEventListener('touchend', handleEnd)
    }
  }, [railDrag, setRailW])

  const startRailDrag = useCallback((clientX: number) => {
    railDragStartX.current = clientX
    railDragStartW.current = railW
    setRailDrag(true)
  }, [railW])
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
  // Excalidraw applies its (empty) initialData scene asynchronously, AFTER the
  // excalidrawAPI callback hands us the api — so a synchronous first
  // updateScene from the build effect gets wiped by that init (prod dogfood
  // 2026-06-20: build committed 46 elements, excalidraw reset to 0 a tick
  // later with no updateScene of our own). The OLD code dodged this only by
  // accident — its `await Promise.all(pageRasters)` delayed the first commit
  // past init. Gate the first commit on excalidraw's first onChange (fires
  // once it has initialised), with a timeout fallback so a quiet init can't
  // hang the board.
  const excaliReadyRef = useRef<Promise<void> | null>(null)
  const excaliReadyResolve = useRef<(() => void) | null>(null)
  if (!excaliReadyRef.current) {
    excaliReadyRef.current = new Promise<void>((res) => { excaliReadyResolve.current = res })
  }

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  // Resolved once per mount — the board lives inside the themed DOM, so the
  // semantic tokens (--moss/--rose/--ochre/...) are available by now.
  const colors = useMemo(() => readBoardColors(), [])
  // Stable identity — cheap hygiene so a re-render can't hand excalidraw a new
  // initialData object (the real first-commit wipe is the mount race handled by
  // excaliReadyRef above, not this).
  const initialData = useMemo(
    () => ({ appState: { viewBackgroundColor: colors.canvas } }),
    [colors.canvas],
  )

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
      // Build the layout inputs from `page_sizes` — exact page boxes WITHOUT
      // fetching a single raster. Was: `await Promise.all(loadPageImage…)` over
      // every page, so the canvas stayed blank until the LAST byte of a
      // 20+-page group landed (the real "白板慢", not the layout). Now structure
      // + rail + circles paint immediately and the rasters stream in below.
      const docInputs: BoardDocInput[] = []
      for (const fn of Object.keys(report.group)) {
        const summary = docSummaries.find(d => d.filename === fn)
        const ext = summary?.ext ?? (fn.includes('.') ? fn.split('.').pop()! : '')
        let sizes = summary?.page_sizes
        if (!sizes || !sizes.length) {
          // No sidecar dims (un-backfilled / compute failure): page count from
          // the sidecar, else the largest page any evidence mentions; box each
          // at A4 — the raster scales into it on arrival.
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
          sizes = Array.from({ length: pageCount }, () => [A4_FALLBACK.w, A4_FALLBACK.h])
        }
        const pages = sizes.map(([w, h], i) => ({ page: i + 1, w, h }))
        docInputs.push({ name: fn, ext, pages })
      }
      if (cancelled || !api) return

      // Few-paged docs first (anchor 报价单/订单/收货单-shaped docs cluster
      // left, a 18-page appendix goes right) — cross-doc checks then zoom to
      // ADJACENT pages instead of spanning the whole board (dogfood
      // 2026-06-11). Content-agnostic: page count only, no doc-type smarts.
      docInputs.sort((a, b) => a.pages.length - b.pages.length)

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
      // Blank-page placeholders (rectangles) + captions — drawn instantly so the
      // board has structure before any raster. Per-check circles/arrows mount on
      // demand via applyCheck (user 2026-06-11: all checks at once = 一板的线, 乱).
      // Each rectangle is swapped for its image (same id) once the raster lands
      // (the stream loop below). Trap #2 (prod dogfood 2026-06-20): committing
      // image skeletons up front instead of rectangles left the canvas blank —
      // convertToExcalidrawElements drops an image skeleton whose file isn't
      // registered yet, and the whole batch with it.
      const skeletons = buildPagePlaceholders([...laid.values()], colors)
      // Wait for excalidraw to finish initialising before the first commit, or
      // it resets our scene to the empty initialData a tick later (mount race,
      // see excaliReadyRef). Fallback timeout so a quiet init can't hang.
      await Promise.race([
        excaliReadyRef.current,
        new Promise<void>((r) => setTimeout(r, 1000)),
      ])
      if (cancelled || !api) return
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

      // ── Stream the page rasters in, visible pages first ──────────────────
      // No barrier: each page registers its file then swaps its placeholder
      // rectangle for the image (same id) the instant it lands, so the
      // initial-view pages (the first located check's cited docs) fill before
      // the long-tail appendix pages. HTTP/2 multiplexes the requests; this
      // order is just a priority hint. Guarded so a close / run-switch
      // mid-stream is a no-op.
      const created = Date.now()
      const prio = new Set<string>()
      if (firstIdx >= 0) {
        for (const e of report.checks[firstIdx]?.evidence ?? []) {
          if (typeof e?.doc === 'string' && e.doc) prio.add(e.doc)
        }
      }
      const plans = docInputs.flatMap(d => d.pages.map(p => ({ fn: d.name, page: p.page })))
      plans.sort((a, b) => (prio.has(b.fn) ? 1 : 0) - (prio.has(a.fn) ? 1 : 0))
      for (const pl of plans) {
        void loadPageImage(slug, pl.fn, pl.page).then(img => {
          if (cancelled || !mountedRef.current || !api || !img) return
          const id = imgId(pl.fn, pl.page)
          // File FIRST — convertToExcalidrawElements drops an image skeleton
          // whose file isn't registered (trap #2); registering before convert
          // is the proven render path.
          api.addFiles([{
            id: id as BinaryFileData['id'],
            dataURL: img.dataURL as BinaryFileData['dataURL'],
            mimeType: img.mimeType as BinaryFileData['mimeType'],
            created,
          }])
          // Swap the placeholder rectangle for the image, reusing the CURRENT
          // element's bounds (focusCheck may have relaid the page since build).
          const cur = api.getSceneElements()
          const ph = cur.find(e => e.id === id)
          if (!ph || ph.type === 'image') return // gone (run switch) or already swapped
          const [imgEl] = convertToExcalidrawElements(
            [{
              type: 'image', id, fileId: id,
              x: ph.x, y: ph.y, width: ph.width, height: ph.height, locked: true,
            }] as never,
            { regenerateIds: false },
          )
          if (!imgEl) return // convert dropped it (shouldn't happen — file is registered)
          api.updateScene({ elements: cur.map(e => (e.id === id ? imgEl : e)) })
        })
      }
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
      // arrow-{idx} plus the -{k} suffixed pair arrows of a many-match check
      e => e.id.startsWith(prefix) || e.id === arrowId(idx)
        || e.id.startsWith(`${arrowId(idx)}-`),
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
    // First onChange = excalidraw has initialised its scene; release the build
    // effect to commit (the mount-race gate, see excaliReadyRef).
    if (excaliReadyResolve.current) {
      excaliReadyResolve.current()
      excaliReadyResolve.current = null
    }
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
      // D1: anchor each note back onto the page it sits over — same payload,
      // same debounce, no extra UI. sceneDataRef.laid is the LATEST layout
      // (focusCheck relayouts write back into the ref); before the scene
      // exists onChange can't reach here (sceneReady guard above).
      const laid = sceneDataRef.current?.laid ?? new Map<string, LaidPage>()
      useBoard.getState().saveNotes(
        slug,
        entry.report.run_id,
        user.map(e => JSON.parse(JSON.stringify(e)) as unknown),
        annotateUserElements(user, laid),
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
        {/* Close lives in the RAIL header (our chrome) — the old floating
            top-right ✕ sat under excalidraw's Library island in fullscreen
            and the user couldn't find a way back (dogfood 2026-06-11).
            Loading/error/empty states have no rail, so keep a floating ✕
            for those only. */}
        {(error || !entry?.report) && (
          <button
            type="button"
            className="absolute top-2 right-2 z-10 p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
            aria-label={t('board.close.aria')}
            title={t('board.close')}
            onClick={onClose}
          >
            <X size={16} />
          </button>
        )}

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
                spatial layer. Collapses to a numbered mini rail (the numbers
                match the canvas's unlocated-evidence badges) and the right
                edge drags to resize — same vocabulary as Shell.tsx, but the
                board owns its own flex layout so it can't reuse Shell. */}
            {railCollapsed ? (
              <div
                className="shrink-0 border-r border-rule-soft overflow-y-auto font-mono text-sm flex flex-col items-center py-2 gap-1"
                style={{ width: RAIL_MINI_W }}
              >
                <button
                  type="button"
                  className="p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
                  aria-label={t('board.rail.expand.aria')}
                  title={t('board.rail.expand')}
                  onClick={toggleRail}
                >
                  <PanelLeftOpen size={16} />
                </button>
                <button
                  type="button"
                  data-testid="board-annotate-mini"
                  aria-pressed={annotating}
                  className={`p-1 rounded-sm ${annotating ? 'text-ochre bg-paper-3' : 'text-ink-3 hover:text-ink hover:bg-paper-2'}`}
                  aria-label={t('board.annotate.aria')}
                  title={annotating ? t('board.annotate.done') : t('board.annotate')}
                  onClick={toggleAnnotate}
                >
                  <Pencil size={16} />
                </button>
                {entry.report.checks.map((c, i) => (
                  <button
                    key={i}
                    type="button"
                    data-testid={`board-check-mini-${i}`}
                    aria-label={c.rule}
                    aria-current={activeCheck === i}
                    title={c.rule}
                    onClick={() => focusCheck(i)}
                    className={`relative w-7 h-7 shrink-0 rounded-sm flex items-center justify-center text-xs ${STATUS_GLYPH[c.status].cls} ${
                      activeCheck === i
                        ? 'bg-paper-3 ring-1 ring-ochre'
                        : 'hover:bg-paper-2'
                    }`}
                  >
                    {i + 1}
                    {c.status === 'fail' && (
                      // Collapsed rail hides the rule text, so a failing check
                      // would read as just another number — a corner dot keeps
                      // "something's wrong here" scannable at 48px.
                      <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 rounded-full bg-rose" aria-hidden="true" />
                    )}
                  </button>
                ))}
              </div>
            ) : (
              <div
                className="shrink-0 border-r border-rule-soft overflow-y-auto font-mono text-sm"
                style={{ width: railW }}
              >
                <div className="px-3 py-2 border-b border-rule-soft text-ink font-semibold flex items-center">
                  {t('board.checks.title')}
                  <span className="ml-2 text-ink-4 text-xs font-normal">
                    {entry.report.checks.filter(c => c.status === 'pass').length}/{entry.report.checks.length}
                  </span>
                  <button
                    type="button"
                    data-testid="board-annotate"
                    aria-pressed={annotating}
                    className={`ml-auto p-1 rounded-sm ${annotating ? 'text-ochre bg-paper-3' : 'text-ink-3 hover:text-ink hover:bg-paper-2'}`}
                    aria-label={t('board.annotate.aria')}
                    title={annotating ? t('board.annotate.done') : t('board.annotate')}
                    onClick={toggleAnnotate}
                  >
                    <Pencil size={16} />
                  </button>
                  <button
                    type="button"
                    className="ml-1 p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
                    aria-label={t('board.rail.collapse.aria')}
                    title={t('board.rail.collapse')}
                    onClick={toggleRail}
                  >
                    <PanelLeftClose size={16} />
                  </button>
                  <button
                    type="button"
                    className="ml-1 p-1 rounded-sm text-ink-3 hover:text-ink hover:bg-paper-2"
                    aria-label={t('board.close.aria')}
                    title={t('board.close')}
                    onClick={onClose}
                  >
                    <X size={16} />
                  </button>
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
                      <span className={`shrink-0 tabular-nums text-ink-4`}>{i + 1}</span>
                      <span className={`${STATUS_GLYPH[c.status].cls} shrink-0`}>
                        {STATUS_GLYPH[c.status].glyph}
                      </span>
                      <span className="text-ink min-w-0 break-words">{c.rule}</span>
                    </div>
                    {(c.evidence ?? []).map((e, j) => (
                      <div key={j} className="pl-9 text-xs text-ink-4 break-words">
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
            )}

            {/* Resize handle — only while expanded. Sits on the rail's right
                edge; ochre on hover/active, same as Shell's .resizer. */}
            {!railCollapsed && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label={t('board.rail.resize')}
                title={t('board.rail.resize')}
                className={`relative shrink-0 w-2 -ml-1 z-10 cursor-col-resize self-stretch flex items-center justify-center group ${railDrag ? 'select-none' : ''}`}
                onMouseDown={(e) => { e.preventDefault(); startRailDrag(e.clientX) }}
                onTouchStart={(e) => { if (e.touches.length > 0) startRailDrag(e.touches[0].clientX) }}
              >
                <span className={`w-[3px] h-8 rounded-sm transition-colors ${railDrag ? 'bg-ochre' : 'bg-transparent group-hover:bg-ochre'}`} />
              </div>
            )}

            <div className="flex-1 min-w-0">
              <Excalidraw
                excalidrawAPI={setApi}
                viewModeEnabled={!annotating}
                onChange={onChange}
                initialData={initialData}
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
