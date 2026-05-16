// frontend/src/stores/docs.ts
import { create } from 'zustand'

import { deleteProjectDoc, listProjectDocs } from '../lib/api'
import type { DocSummary } from '../types/review'

interface State {
  byProject: Record<string, DocSummary[]>
  loading: boolean
  refresh: (projectId: string) => Promise<void>
  /** Remove a doc from the server and drop it from local state. The caller
   *  (review overlay) decides where to navigate next. */
  remove: (projectId: string, filename: string) => Promise<void>
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
  remove: async (projectId, filename) => {
    await deleteProjectDoc(projectId, filename)
    set((s) => {
      const list = s.byProject[projectId] ?? []
      return {
        byProject: {
          ...s.byProject,
          [projectId]: list.filter((d) => d.filename !== filename),
        },
      }
    })
  },
}))
