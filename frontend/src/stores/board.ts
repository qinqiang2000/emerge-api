// Audit-board data cache (`useBoard`) — per-slug, cache-first, mirrors
// `useBench`.
//
// `load(slug)` does the whole board fetch fan-out once:
//   1. `GET /lab/projects/{slug}/audit/latest` → report (null = never audited,
//      a valid empty state);
//   2. aggregate every check's evidence quotes BY DOC and fire ONE
//      locate-quotes POST per doc (page hints included), then map each result
//      back to its (checkIdx, evIdx) via the request-order index the route
//      echoes.
// Rects only ever live here + the canvas render layer (render-only red line —
// they never reach any agent/LLM context).
//
// Board notes (user-drawn excalidraw elements) are loaded once per slug and
// saved through a 1s debounce so freedraw strokes don't PUT per pointer-move.
//
// Selector discipline: components must select plain slices
// (`s.byProject[slug]`) — never `?? []` / `.filter` / object literals inside a
// selector (repo trap `project_zustand_selector_fresh_ref_loop`).

import { create } from 'zustand'

import {
  fetchTextlayer,
  getAuditLatest,
  getBoardNotes,
  putBoardNotes,
  type AuditLatestReport,
  type BoardAnnotation,
  type BoardNotesPayload,
} from '../lib/api'
import { fetchLocateQuotes } from '../lib/locate'

/** Max (doc, page) textlayer warms per board load — the self-heal pass for
 *  scanned pages whose OCR sidecar is cold (see `load`). */
const WARM_CAP = 8

/** Key for one evidence row's location: `${checkIdx}-${evIdx}`. */
export const evKey = (checkIdx: number, evIdx: number) => `${checkIdx}-${evIdx}`

export interface BoardLocation {
  rects: number[][]
  page: number | null
  status: string
  score: number
}

export interface BoardEntry {
  /** null = project has never been audited (valid empty state) */
  report: AuditLatestReport | null
  /** located evidence keyed by `evKey(checkIdx, evIdx)`; unlocated/missing
   *  evidence simply has no entry */
  locations: Record<string, BoardLocation>
}

interface State {
  byProject: Record<string, BoardEntry>
  loading: Record<string, boolean>
  errors: Record<string, string>
  /** key present = notes fetched (null = none on the server) */
  notesByProject: Record<string, BoardNotesPayload | null>
  load: (slug: string) => Promise<void>
  invalidate: (slug: string) => void
  loadNotes: (slug: string) => Promise<void>
  /** Debounced (1s) persist of the user-drawn elements for the current run.
   *  The local cache updates immediately so close→reopen restores instantly.
   *  `annotations` (D1) is the anchor sidecar computed from the same elements
   *  — it rides the same payload/debounce, never a second pipeline. */
  saveNotes: (slug: string, runId: string, elements: unknown[], annotations?: BoardAnnotation[]) => void
  reset: () => void
}

// Debounce timers live outside the store — they're imperative bookkeeping,
// not render state.
const noteTimers: Record<string, ReturnType<typeof setTimeout>> = {}
const NOTES_DEBOUNCE_MS = 1000

export const useBoard = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  errors: {},
  notesByProject: {},

  reset: () => set({ byProject: {}, loading: {}, errors: {}, notesByProject: {} }),

  invalidate: (slug) =>
    set((s) => {
      const byProject = { ...s.byProject }; delete byProject[slug]
      const errors = { ...s.errors }; delete errors[slug]
      const notesByProject = { ...s.notesByProject }; delete notesByProject[slug]
      return { byProject, errors, notesByProject }
    }),

  load: async (slug) => {
    if (slug in get().byProject) return // cached — skip fetch
    if (get().loading[slug]) {
      // dedupe in-flight: park on the subscribe and resolve when the slug
      // lands in byProject (mirrors useBench).
      return new Promise<void>((resolve) => {
        const unsub = useBoard.subscribe((s) => {
          if (slug in s.byProject || !s.loading[slug]) {
            unsub(); resolve()
          }
        })
      })
    }
    set((s) => {
      const errors = { ...s.errors }; delete errors[slug]
      return { loading: { ...s.loading, [slug]: true }, errors }
    })
    try {
      const report = await getAuditLatest(slug)
      const locations: Record<string, BoardLocation> = {}
      if (report) {
        // Aggregate quotes per doc → one locate-quotes POST per doc. The
        // route echoes input order via `index`, so a parallel backrefs array
        // maps each result to its (checkIdx, evIdx).
        const byDoc = new Map<string, { quotes: { page?: number | null; quote: string }[]; keys: string[] }>()
        report.checks.forEach((c, i) => {
          (c.evidence ?? []).forEach((e, j) => {
            if (typeof e?.doc !== 'string' || !e.doc || typeof e.quote !== 'string' || !e.quote) return
            let bucket = byDoc.get(e.doc)
            if (!bucket) { bucket = { quotes: [], keys: [] }; byDoc.set(e.doc, bucket) }
            bucket.quotes.push({ page: e.page ?? null, quote: e.quote })
            bucket.keys.push(evKey(i, j))
          })
        })
        const locateDocs = async (entries: [string, { quotes: { page?: number | null; quote: string }[]; keys: string[] }][]) => {
          await Promise.all(
            entries.map(async ([doc, { quotes, keys }]) => {
              // fetchLocateQuotes is best-effort ([] on any failure) — a doc
              // that 404s degrades to badges, never breaks the board.
              const results = await fetchLocateQuotes(slug, doc, quotes)
              for (const r of results) {
                const key = keys[r.index]
                if (!key) continue
                locations[key] = {
                  rects: Array.isArray(r.rects) ? r.rects : [],
                  page: r.page ?? null,
                  status: r.status ?? 'none',
                  score: r.score ?? 0,
                }
              }
            }),
          )
        }
        await locateDocs([...byDoc.entries()])

        // Self-heal pass (scanned docs): locate-quotes reads WARM sidecars
        // only (LLM-free render path, skip_ocr) — a quote on a scanned page
        // whose OCR sidecar is cold can never hit. GET /textlayer warms
        // fitz+OCR server-side (the review viewer's own lazy-warm), so warm
        // the cited pages of missed evidence once, then re-locate those docs
        // (prod dogfood 2026-06-11: 报价单.pdf is a scan — every quote missed
        // until the first /textlayer touch, then located fine).
        const missed = new Map<string, { quotes: { page?: number | null; quote: string }[]; keys: string[] }>()
        const warmPages = new Set<string>()
        report.checks.forEach((c, i) => {
          (c.evidence ?? []).forEach((e, j) => {
            if (typeof e?.doc !== 'string' || !e.doc || typeof e.quote !== 'string' || !e.quote) return
            const loc = locations[evKey(i, j)]
            if (loc && loc.status !== 'none' && loc.rects.length) return
            let bucket = missed.get(e.doc)
            if (!bucket) { bucket = { quotes: [], keys: [] }; missed.set(e.doc, bucket) }
            bucket.quotes.push({ page: e.page ?? null, quote: e.quote })
            bucket.keys.push(evKey(i, j))
            warmPages.add(`${e.doc}\u0000${e.page ?? 1}`)
          })
        })
        if (missed.size) {
          await Promise.all(
            [...warmPages].slice(0, WARM_CAP).map((k) => {
              const [doc, page] = k.split('\u0000')
              return fetchTextlayer(slug, doc, Number(page)).catch(() => null)
            }),
          )
          await locateDocs([...missed.entries()])
        }
      }
      set((s) => ({ byProject: { ...s.byProject, [slug]: { report, locations } } }))
    } catch (e) {
      set((s) => ({
        errors: { ...s.errors, [slug]: e instanceof Error ? e.message : String(e) },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[slug]
        return { loading: next }
      })
    }
  },

  loadNotes: async (slug) => {
    if (slug in get().notesByProject) return // cached (null = "none") — skip
    const notes = await getBoardNotes(slug) // permissive: null on any failure
    set((s) => ({ notesByProject: { ...s.notesByProject, [slug]: notes } }))
  },

  saveNotes: (slug, runId, elements, annotations) => {
    const payload: BoardNotesPayload = annotations
      ? { run_id: runId, elements, annotations }
      : { run_id: runId, elements }
    set((s) => ({ notesByProject: { ...s.notesByProject, [slug]: payload } }))
    if (noteTimers[slug]) clearTimeout(noteTimers[slug])
    noteTimers[slug] = setTimeout(() => {
      delete noteTimers[slug]
      // fire-and-forget — notes are an enhancement; a failed PUT must never
      // throw into the canvas onChange path. The next edit retries.
      void putBoardNotes(slug, payload).catch(() => {})
    }, NOTES_DEBOUNCE_MS)
  },
}))
