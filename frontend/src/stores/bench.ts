// Project-level Bench (prompt × model leaderboard) cache.
//
// Bench is a pure read-only aggregator surfaced from the FSSpine
// `experiments/` group header → `?bench=1` modal. The store keeps one
// `BenchResponse` per slug and dedupes concurrent loads on the same key so
// the matrix doesn't double-fetch when both the headline + rail subscribe
// at mount.
//
// Mutation invalidation lives in chat store (T9 — when a tool result
// promotes / re-runs / creates / archives / deletes an experiment, or
// rewrites a prompt / switches the active prompt / model, the chat slice
// calls `useBench.getState().invalidate(slug)`). The store itself does
// not subscribe to mutations.

import { create } from 'zustand'

import { getBench } from '../lib/api'
import type { BenchResponse } from '../types/bench'

interface State {
  byProject: Record<string, BenchResponse>
  loading: Record<string, boolean>
  load: (slug: string) => Promise<void>
  invalidate: (slug: string) => void
  reset: () => void
}

export const useBench = create<State>((set, get) => ({
  byProject: {},
  loading: {},

  reset: () => set({ byProject: {}, loading: {} }),

  invalidate: (slug) =>
    set((s) => {
      const byProject = { ...s.byProject }; delete byProject[slug]
      return { byProject }
    }),

  load: async (slug) => {
    if (slug in get().byProject) return  // cached — skip fetch
    if (get().loading[slug]) {
      // dedupe in-flight: park on the subscribe and resolve when the
      // slug lands in byProject (mirrors useExperiments pattern).
      return new Promise<void>((resolve) => {
        const unsub = useBench.subscribe((s) => {
          if (slug in s.byProject || !s.loading[slug]) {
            unsub(); resolve()
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [slug]: true } }))
    try {
      const data = await getBench(slug)
      set((s) => ({ byProject: { ...s.byProject, [slug]: data } }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[slug]
        return { loading: next }
      })
    }
  },
}))
