// Compare-board data cache (`useCompareBoard`) — the same cache-first shape as
// `useReviewBoard`, but keyed by the whole comparison (slug + the two eval
// timestamps), not by slug alone: one project can hold many comparisons and
// they must not evict each other.
//
// Selector discipline: components select plain slices (`s.byKey[key]`) —
// never `?? []` / `.filter` / object literals inside a selector (repo trap
// `project_zustand_selector_fresh_ref_loop`). Coalesce in a component useMemo.

import { create } from 'zustand'

import { getCompareBoard, type CompareBoardPayload } from '../lib/api'

export function compareKey(slug: string, a: string, b: string): string {
  return `${slug}|${a}|${b}`
}

interface State {
  byKey: Record<string, CompareBoardPayload>
  loading: Record<string, boolean>
  errors: Record<string, string>
  load: (slug: string, a: string, b: string) => Promise<void>
  invalidate: (slug: string) => void
  reset: () => void
}

export const useCompareBoard = create<State>((set, get) => ({
  byKey: {},
  loading: {},
  errors: {},

  reset: () => set({ byKey: {}, loading: {}, errors: {} }),

  // Project-scoped invalidation: a re-run inside `slug` can change any of its
  // comparisons, so drop every key that belongs to it.
  invalidate: (slug) =>
    set((s) => {
      const prefix = `${slug}|`
      const byKey = { ...s.byKey }
      const errors = { ...s.errors }
      for (const k of Object.keys(byKey)) if (k.startsWith(prefix)) delete byKey[k]
      for (const k of Object.keys(errors)) if (k.startsWith(prefix)) delete errors[k]
      return { byKey, errors }
    }),

  load: async (slug, a, b) => {
    const key = compareKey(slug, a, b)
    if (key in get().byKey) return // cached — skip fetch
    if (get().loading[key]) {
      // dedupe in-flight: park on the subscribe and resolve when the key
      // lands in byKey (mirrors useReviewBoard).
      return new Promise<void>((resolve) => {
        const unsub = useCompareBoard.subscribe((s) => {
          if (key in s.byKey || !s.loading[key]) {
            unsub(); resolve()
          }
        })
      })
    }
    set((s) => {
      const errors = { ...s.errors }; delete errors[key]
      return { loading: { ...s.loading, [key]: true }, errors }
    })
    try {
      const payload = await getCompareBoard(slug, a, b)
      set((s) => ({ byKey: { ...s.byKey, [key]: payload } }))
    } catch (e) {
      set((s) => ({
        errors: { ...s.errors, [key]: e instanceof Error ? e.message : String(e) },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[key]
        return { loading: next }
      })
    }
  },
}))
