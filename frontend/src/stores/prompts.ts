import { create } from 'zustand'
import type { SchemaField } from './schema'

export interface PromptRow {
  prompt_id: string
  label: string
  derived_from: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ActivePrompt {
  prompt_id: string
  label: string
  schema: SchemaField[]
  global_notes: string
  derived_from: string | null
  created_at: string
  updated_at: string
}

interface State {
  list: Record<string, PromptRow[]>
  activeByProject: Record<string, ActivePrompt | undefined>
  /** `projectId → promptId → schema`. A prediction must be rendered through
   *  the schema of the prompt that PRODUCED it (`_run.prompt_id`), not the
   *  project's currently-active prompt — otherwise every experiment whose
   *  prompt differs from the active one silently loses the fields the active
   *  schema doesn't declare. `null` marks a fetch that 404'd (prompt deleted),
   *  so callers fall back to the project schema without re-fetching forever. */
  schemaById: Record<string, Record<string, SchemaField[] | null>>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<void>
  loadPromptSchema: (projectId: string, promptId: string) => Promise<void>
  invalidate: (projectId: string) => void
  reset: () => void
}

export const usePrompts = create<State>((set, get) => ({
  list: {},
  activeByProject: {},
  schemaById: {},
  loading: {},

  reset: () => set({ list: {}, activeByProject: {}, schemaById: {}, loading: {} }),

  // Drops both caches for the project. Nothing here schedules a refetch —
  // callers must either call load() right after or be sure a mount-time
  // effect (e.g. FSSpine's selectedSlug effect) will refill. Otherwise the
  // spine flashes "(none yet)" and Quick-look's active-prompt readers see
  // undefined until the next page mount. Prefer patching activeByProject
  // in place when you already know the new value.
  invalidate: (projectId) =>
    set((s) => {
      const list = { ...s.list }; delete list[projectId]
      const active = { ...s.activeByProject }; delete active[projectId]
      const schemas = { ...s.schemaById }; delete schemas[projectId]
      return { list, activeByProject: active, schemaById: schemas }
    }),

  load: async (projectId) => {
    if (get().list[projectId]) return  // cached — skip fetch
    if (get().loading[projectId]) {
      // dedupe in-flight
      return new Promise<void>((resolve) => {
        const unsub = usePrompts.subscribe((s) => {
          if (!s.loading[projectId]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    try {
      const [listResp, activeResp] = await Promise.all([
        fetch(`/lab/projects/${encodeURIComponent(projectId)}/prompts`),
        fetch(`/lab/projects/${encodeURIComponent(projectId)}/prompts/active`),
      ])
      const list = listResp.ok ? (await listResp.json() as PromptRow[]) : []
      const active = activeResp.ok ? (await activeResp.json() as ActivePrompt) : undefined
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

  loadPromptSchema: async (projectId, promptId) => {
    // Cached — `null` (a 404) counts as cached, so a deleted prompt is fetched
    // once and then permanently falls back to the project schema.
    if (promptId in (get().schemaById[projectId] ?? {})) return
    const key = `schema:${projectId}:${promptId}`
    if (get().loading[key]) {
      return new Promise<void>((resolve) => {
        const unsub = usePrompts.subscribe((s) => {
          if (!s.loading[key]) { unsub(); resolve() }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [key]: true } }))
    try {
      const resp = await fetch(
        `/lab/projects/${encodeURIComponent(projectId)}/prompts/${encodeURIComponent(promptId)}`,
      )
      const schema = resp.ok ? ((await resp.json()) as ActivePrompt).schema ?? null : null
      set((s) => ({
        schemaById: {
          ...s.schemaById,
          [projectId]: { ...(s.schemaById[projectId] ?? {}), [promptId]: schema },
        },
      }))
    } finally {
      set((s) => {
        const next = { ...s.loading }; delete next[key]
        return { loading: next }
      })
    }
  },
}))
