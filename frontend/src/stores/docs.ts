// frontend/src/stores/docs.ts
import { create } from 'zustand'

import { listProjectDocs } from '../lib/api'
import type { DocSummary } from '../types/review'

interface State {
  byProject: Record<string, DocSummary[]>
  loading: boolean
  refresh: (projectId: string) => Promise<void>
}

export const useDocs = create<State>((set) => ({
  byProject: {},
  loading: false,
  refresh: async (projectId) => {
    set({ loading: true })
    try {
      const docs = await listProjectDocs(projectId)
      set((s) => ({ byProject: { ...s.byProject, [projectId]: docs }, loading: false }))
    } catch {
      set({ loading: false })
    }
  },
}))
