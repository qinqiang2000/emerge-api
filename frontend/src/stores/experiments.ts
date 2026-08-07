import { create } from 'zustand'

import { listExperiments } from '../lib/api'
import type { ExperimentSummary } from '../types/review'

interface State {
  list: Record<string, ExperimentSummary[]>
  loading: Record<string, boolean>
  /** Bumped by `invalidate`. A fetch captures it at start and drops its rows
   *  if it moved mid-flight — that snapshot predates the mutation that
   *  invalidated it. Without this the store is cache-first over stale rows
   *  and nothing ever re-fetches them. */
  epoch: Record<string, number>
  load: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useExperiments = create<State>((set, get) => ({
  list: {},
  loading: {},
  epoch: {},

  reset: () => set({ list: {}, loading: {}, epoch: {} }),

  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      return { list, epoch: { ...s.epoch, [projectId]: (s.epoch[projectId] ?? 0) + 1 } }
    }),

  load: async (projectId) => {
    if (get().list[projectId]) return  // cached — skip fetch
    if (get().loading[projectId]) {
      // dedupe in-flight
      await new Promise<void>((resolve) => {
        const unsub = useExperiments.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
      // The fetch we rode on may have been invalidated while in flight (it
      // dropped its rows), so the cache can still be empty here. Re-enter
      // rather than return: chat invalidates + reloads on every experiment
      // tool result, and back-to-back results in one agent turn land inside
      // each other's fetch window — riding the older fetch would freeze the
      // spine's `experiments/` list at a partial snapshot until a reload.
      if (get().list[projectId]) return
      return get().load(projectId)
    }
    const epoch = get().epoch[projectId] ?? 0
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const rows = await listExperiments(projectId)
      if ((get().epoch[projectId] ?? 0) === epoch) {
        set((s) => ({ list: { ...s.list, [projectId]: rows } }))
      }
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[projectId]
        return { loading: next }
      })
    }
  },
}))
