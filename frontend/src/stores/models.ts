import { create } from 'zustand'

export interface ModelRow {
  model_id: string
  label: string
  provider: 'anthropic' | 'openai' | 'google'
  provider_model_id: string
  is_active: boolean
  created_at: string
}

export interface ActiveModel {
  model_id: string
  label: string
  provider: 'anthropic' | 'openai' | 'google'
  provider_model_id: string
  params: Record<string, unknown>
  created_at: string
}

interface State {
  list: Record<string, ModelRow[]>
  activeByProject: Record<string, ActiveModel | undefined>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useModels = create<State>((set, get) => ({
  list: {},
  activeByProject: {},
  loading: {},

  reset: () => set({ list: {}, activeByProject: {}, loading: {} }),

  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      const active = { ...s.activeByProject }; delete active[projectId]
      return { list, activeByProject: active }
    }),

  load: async (projectId) => {
    if (get().list[projectId]) return  // cached — skip fetch
    if (get().loading[projectId]) {
      return new Promise<void>((resolve) => {
        const unsub = useModels.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const [listResp, activeResp] = await Promise.all([
        fetch(`/lab/projects/${projectId}/models`),
        fetch(`/lab/projects/${projectId}/models/active`),
      ])
      const list = listResp.ok ? (await listResp.json() as ModelRow[]) : []
      const active = activeResp.ok ? (await activeResp.json() as ActiveModel) : undefined
      set((s) => ({
        list: { ...s.list, [projectId]: list },
        activeByProject: { ...s.activeByProject, [projectId]: active },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[projectId]
        return { loading: next }
      })
    }
  },
}))
