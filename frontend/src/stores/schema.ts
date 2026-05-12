import { create } from 'zustand'

export interface SchemaField {
  name: string
  type: string
  description: string
  required?: boolean
  examples?: string[] | null
  enum?: string[] | null
  children?: SchemaField[] | null
}

interface State {
  byProject: Record<string, SchemaField[]>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<SchemaField[]>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const useSchema = create<State>((set, get) => ({
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
    const cached = get().byProject[projectId]
    if (cached) return cached
    if (get().loading[projectId]) {
      // dedupe in-flight
      return new Promise((resolve) => {
        const unsub = useSchema.subscribe((s) => {
          if (s.byProject[projectId]) {
            unsub()
            resolve(s.byProject[projectId])
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const r = await fetch(`/lab/projects/${projectId}/schema`)
      const fields: SchemaField[] = r.ok ? await r.json() : []
      set((s) => ({
        byProject: { ...s.byProject, [projectId]: fields },
        loading: { ...s.loading, [projectId]: false },
      }))
      return fields
    } catch {
      set((s) => ({ loading: { ...s.loading, [projectId]: false } }))
      return []
    }
  },
}))
