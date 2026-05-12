import { create } from 'zustand'

import { listExperiments } from '../lib/api'
import type { ExperimentSummary } from '../types/review'

interface State {
  list: Record<string, ExperimentSummary[]>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useExperiments = create<State>((set, get) => ({
  list: {},
  loading: {},

  reset: () => set({ list: {}, loading: {} }),

  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      return { list }
    }),

  load: async (projectId) => {
    if (get().list[projectId]) return  // cached — skip fetch
    if (get().loading[projectId]) {
      // dedupe in-flight
      return new Promise<void>((resolve) => {
        const unsub = useExperiments.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const rows = await listExperiments(projectId)
      set((s) => ({ list: { ...s.list, [projectId]: rows } }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[projectId]
        return { loading: next }
      })
    }
  },
}))
