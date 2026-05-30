import { create } from 'zustand'
import { fetchLocate, type FieldLocation } from '../lib/locate'
import { fetchTextlayer } from '../lib/api'

/**
 * Field source-grounding state.
 *
 * Results are cached per (filename, tabKey) so switching tabs re-resolves with
 * that tab's entities/evidence, and reopening a doc starts clean (review.open()
 * calls reset()). `focusedPath` drives which field's rects are painted.
 *
 * RED LINE: rects live only here + the render layer. Never feed any value from
 * this store into chat / agent / extract / proposer paths.
 */

function cacheKey(filename: string, tabKey: string): string {
  return `${filename}::${tabKey}`
}

// Keys with a loadFor pass in flight. `byKey` only records a *completed* attempt,
// so without this two near-simultaneous triggers (the debounced pre-load + a
// field-click force-load) would both pass the `key in byKey` guard and fire a
// duplicate ground+locate (and a duplicate ground is a duplicate LLM call).
const _inflight = new Set<string>()

// (filename, tabKey, page) we've already warmed-OCR + re-located for. locate
// reads warm textlayer sidecars but never warms them itself (skip_ocr=True keeps
// it fast + freeze-free + provider-free, see INSIGHTS "/locate must run OFF the
// event loop"). So when a field's value lives only in a letterhead IMAGE (absent
// from the page's native text layer), its hint page resolves to `none` until that
// page's OCR sidecar is warm. This set bounds the on-demand warm to once per page
// per tab — a page whose image genuinely has no recoverable text stays none
// instead of looping warm→relocate→none forever.
const _ocrRelocated = new Set<string>()

interface LocateState {
  byKey: Record<string, FieldLocation[]>
  focusedPath: string | null
  /** Entity the focused path belongs to. A multi-entity doc carries the SAME
   *  leaf path (e.g. `invoiceNumber`) once per entity, each on its own page, so
   *  path alone is ambiguous — the highlight/pan must scope to (entity, path)
   *  or every field resolves to entity 0's occurrence. */
  focusedEntity: number | null
  loading: boolean
  /**
   * Pan request: bumped whenever a field is freshly focused so the doc viewer
   * scrolls that field's source rect to center. `seq` is monotonic so each
   * click re-triggers even on the same field; `path` lets the matching page's
   * overlay claim the request (other pages ignore it). Render-only — never fed
   * to any agent/extract path (same red line as `byKey`).
   */
  scrollReq: { seq: number; path: string } | null
  /** Toggle focus on (entity, path): focusing the already-focused pair clears it. */
  focus: (path: string, entityIdx: number) => void
  /** Bump the pan request for `path` (called on focus-in, not on toggle-off). */
  requestScroll: (path: string) => void
  /** Fetch + cache locations for a tab if not already attempted (404 -> [] counts as attempted). */
  loadFor: (
    projectId: string,
    filename: string,
    tabKey: string,
    entities: Record<string, unknown>[],
    evidence: (Record<string, unknown> | null)[] | null,
    /** Reserved (formerly the ground-pass cache target). locate no longer runs a
     *  ground LLM pass on this render path, so it is ignored; kept so callers
     *  needn't change and to document the removed coupling. */
    activeBacking?: '_draft' | '_pending',
  ) => Promise<void>
  /**
   * On-demand single-page OCR + re-locate. Call when a focused field resolved to
   * `none` but has a page hint: the value may live in that page's letterhead
   * image, invisible to locate's fitz-only read of a cold sidecar. We warm that
   * ONE page's OCR (the existing /textlayer route does OCR), then re-run locate
   * for the tab so it reads the now-warm sidecar. Idempotent per (tab, page).
   */
  warmAndRelocate: (
    projectId: string,
    filename: string,
    tabKey: string,
    page: number,
    entities: Record<string, unknown>[],
    evidence: (Record<string, unknown> | null)[] | null,
  ) => Promise<void>
  reset: () => void
}

export const useLocate = create<LocateState>((set, get) => ({
  byKey: {},
  focusedPath: null,
  focusedEntity: null,
  loading: false,
  scrollReq: null,

  focus: (path, entityIdx) => {
    set((s) => {
      const same = s.focusedPath === path && s.focusedEntity === entityIdx
      return same
        ? { focusedPath: null, focusedEntity: null }
        : { focusedPath: path, focusedEntity: entityIdx }
    })
  },

  requestScroll: (path) => {
    set((s) => ({ scrollReq: { seq: (s.scrollReq?.seq ?? 0) + 1, path } }))
  },

  loadFor: async (projectId, filename, tabKey, entities, evidence, _activeBacking = '_draft') => {
    const key = cacheKey(filename, tabKey)
    // `in` check (not truthiness): an empty-array cache still counts as attempted.
    // `_inflight` dedupes a concurrent pass so we never double-fire ground+locate.
    if (key in get().byKey || _inflight.has(key)) return
    if (!entities.length) {
      // nothing to resolve; mark attempted so we don't re-fire on every render
      set((s) => ({ byKey: { ...s.byKey, [key]: [] } }))
      return
    }
    _inflight.add(key)
    set({ loading: true })
    try {
      // locate uses the evidence already on the displayed blob (page hints +
      // verbatim source quotes that extraction emitted). It deliberately does NOT
      // run a ground LLM pass here: this is the click-to-pan render path, and a
      // render aid must never block on an LLM (a slow/unreachable provider would
      // stall "正在定位来源…" for the whole retry window). Docs whose extraction
      // emitted no evidence fall back to the LLM-free value matcher, which is
      // already quite capable; producing source quotes belongs in the
      // extract/label pipeline (warmed into the blob), not lazily on review.
      const locations = await fetchLocate(projectId, filename, entities, evidence)
      set((s) => ({ byKey: { ...s.byKey, [key]: locations }, loading: false }))
    } finally {
      _inflight.delete(key)
    }
  },

  warmAndRelocate: async (projectId, filename, tabKey, page, entities, evidence) => {
    const guard = `${filename}::${tabKey}::${page}`
    if (_ocrRelocated.has(guard) || !entities.length) return
    _ocrRelocated.add(guard)
    set({ loading: true })
    try {
      // Warm the hint page's OCR sidecar (the /textlayer route runs OCR; this is
      // the ONE network call, bounded to the page the user actually inspected).
      await fetchTextlayer(projectId, filename, page)
      // Re-run locate: it now reads the warm sidecar (skip_ocr=True still — the
      // warming happened in /textlayer, not in locate). Overwrite the tab cache.
      const locations = await fetchLocate(projectId, filename, entities, evidence)
      set((s) => ({ byKey: { ...s.byKey, [cacheKey(filename, tabKey)]: locations }, loading: false }))
      // Re-pan to the freshly-resolved rect: the click-time scroll request was
      // consumed while the field was still `none`, so bump it again so the now-
      // located rect scrolls to centre.
      const fp = get().focusedPath
      if (fp) set((s) => ({ scrollReq: { seq: (s.scrollReq?.seq ?? 0) + 1, path: fp } }))
    } catch {
      set({ loading: false })
    }
  },

  reset: () => {
    set({ byKey: {}, focusedPath: null, focusedEntity: null, loading: false, scrollReq: null })
  },
}))

export { cacheKey }
