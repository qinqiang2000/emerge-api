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
  loading: boolean
  /** Toggle focus: focusing the already-focused path clears it. */
  focus: (path: string) => void
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
  loading: false,

  focus: (path) => {
    set((s) => ({ focusedPath: path === s.focusedPath ? null : path }))
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
    set({ byKey: {}, focusedPath: null, loading: false })
  },
}))

export { cacheKey }
