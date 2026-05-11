import { create } from 'zustand'

import { getLatestEval, type EvalSnapshot } from '../lib/api'

interface State {
  // null = fetched, no eval on disk yet; undefined = not fetched yet.
  byProject: Record<string, EvalSnapshot | null>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<EvalSnapshot | null>
  refresh: (projectId: string) => Promise<EvalSnapshot | null>
  invalidate: (projectId: string) => void
  reset: () => void
}

async function fetchSlice(projectId: string): Promise<EvalSnapshot | null> {
  try {
    return await getLatestEval(projectId)
  } catch {
    return null
  }
}

export const useEval = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  reset: () => set({ byProject: {}, loading: {} }),
  invalidate: (projectId) =>
    set((s) => {
      const next = { ...s.byProject }
      delete next[projectId]
      return { byProject: next }
    }),
  load: async (projectId) => {
    if (projectId in get().byProject) return get().byProject[projectId]
    if (get().loading[projectId]) {
      return new Promise((resolve) => {
        const unsub = useEval.subscribe((s) => {
          if (projectId in s.byProject) {
            unsub()
            resolve(s.byProject[projectId])
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
  refresh: async (projectId) => {
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
}))
