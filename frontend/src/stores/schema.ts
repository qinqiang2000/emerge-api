import { create } from 'zustand'

export interface SchemaField {
  name: string
  type: string
  description: string
  required?: boolean
  enum?: string[] | null
  children?: SchemaField[] | null
}

export interface SaveError {
  error_code: string
  error_message_en?: string
}

interface State {
  byProject: Record<string, SchemaField[]>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<SchemaField[]>
  /** Direct human edit of the active prompt. Returns null on success
   *  or a SaveError envelope. On success, byProject is updated so the
   *  UI reflects the persisted state. */
  saveActive: (projectId: string, fields: SchemaField[], globalNotes?: string) => Promise<SaveError | null>
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
      const r = await fetch(`/lab/projects/${encodeURIComponent(projectId)}/schema`)
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

  saveActive: async (projectId, fields, globalNotes) => {
    try {
      const r = await fetch(`/lab/projects/${encodeURIComponent(projectId)}/prompts/active`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema: fields, global_notes: globalNotes ?? '' }),
      })
      if (!r.ok) {
        let detail: SaveError = { error_code: `http_${r.status}` }
        try {
          const j = await r.json()
          detail = j?.detail ?? detail
        } catch { /* not json */ }
        return detail
      }
      const blob = await r.json() as { schema: SchemaField[] }
      const next = blob.schema ?? fields
      set((s) => ({ byProject: { ...s.byProject, [projectId]: next } }))
      return null
    } catch (e) {
      return { error_code: 'network_error', error_message_en: (e as Error).message }
    }
  },
}))
