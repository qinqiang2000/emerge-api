import { create } from 'zustand'
import { fetchLocate, type FieldLocation } from '../lib/locate'

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
    lang?: string,
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

  loadFor: async (projectId, filename, tabKey, entities, evidence, lang) => {
    const key = cacheKey(filename, tabKey)
    // `in` check (not truthiness): an empty-array cache still counts as attempted.
    if (key in get().byKey) return
    if (!entities.length) {
      // nothing to resolve; mark attempted so we don't re-fire on every render
      set((s) => ({ byKey: { ...s.byKey, [key]: [] } }))
      return
    }
    set({ loading: true })
    const locations = await fetchLocate(projectId, filename, entities, evidence, lang)
    set((s) => ({ byKey: { ...s.byKey, [key]: locations }, loading: false }))
  },

  reset: () => {
    set({ byKey: {}, focusedPath: null, loading: false })
  },
}))

export { cacheKey }
