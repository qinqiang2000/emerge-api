import { create } from 'zustand'
import { fetchGround, fetchLocate, hasEvidenceSignal, type FieldLocation } from '../lib/locate'

/**
 * Which prediction blob the grounding result caches into. `_draft` / `_pending`
 * map to themselves; the editable `active` tab is backed by pending when a
 * pre-label is awaiting verification, else by the draft (caller passes the
 * resolved hint). Experiment tabs have their own extracts dir (not groundable
 * here) → null, keep page-level fallback. The entities we actually ground are
 * always the displayed ones, so this is only a cache target, not the source.
 */
function groundTabFor(tabKey: string, activeBacking: '_draft' | '_pending' = '_draft'): '_draft' | '_pending' | null {
  if (tabKey === '_pending') return '_pending'
  if (tabKey === '_draft') return '_draft'
  if (tabKey === 'active') return activeBacking
  return null
}

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
    /** For the `active` tab, which blob backs it: '_pending' when verifying a
     *  pre-label, else '_draft'. Used only as the grounding cache target. */
    activeBacking?: '_draft' | '_pending',
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

  loadFor: async (projectId, filename, tabKey, entities, evidence, activeBacking = '_draft') => {
    const key = cacheKey(filename, tabKey)
    // `in` check (not truthiness): an empty-array cache still counts as attempted.
    if (key in get().byKey) return
    if (!entities.length) {
      // nothing to resolve; mark attempted so we don't re-fire on every render
      set((s) => ({ byKey: { ...s.byKey, [key]: [] } }))
      return
    }
    set({ loading: true })
    // High-precision locate needs the verbatim source quote as its anchor. When
    // the displayed tab carries no evidence, run the grounding pass first (one
    // LLM call, cached server-side) on the displayed entities and locate with it.
    let effective = evidence
    if (!hasEvidenceSignal(evidence)) {
      const tab = groundTabFor(tabKey, activeBacking)
      if (tab) {
        const grounded = await fetchGround(projectId, filename, tab, entities)
        if (grounded) effective = grounded
      }
    }
    const locations = await fetchLocate(projectId, filename, entities, effective)
    set((s) => ({ byKey: { ...s.byKey, [key]: locations }, loading: false }))
  },

  reset: () => {
    set({ byKey: {}, focusedPath: null, focusedEntity: null, loading: false, scrollReq: null })
  },
}))

export { cacheKey }
