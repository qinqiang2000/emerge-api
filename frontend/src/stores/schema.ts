import { create } from 'zustand'
import { usePrompts } from './prompts'

export type FieldTypeName = 'string' | 'number' | 'integer' | 'boolean' | 'object' | 'array'
export type StringFormatName = 'date' | 'date-time' | 'time'

export interface SchemaField {
  /** Named at top level and inside object.properties; null only for array.items. */
  name: string | null
  type: FieldTypeName | string
  description: string
  required?: boolean
  format?: StringFormatName | null
  enum?: string[] | null
  properties?: SchemaField[] | null
  items?: SchemaField | null
  /** Legacy ARRAY_OBJECT shape — kept for type compatibility on read paths
   *  that haven't been migrated yet. Writes use properties/items. */
  children?: SchemaField[] | null
}

export interface SaveError {
  error_code: string
  error_message_en?: string
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

const SAVED_HOLD_MS = 1500

interface State {
  byProject: Record<string, SchemaField[]>
  loading: Record<string, boolean>
  /** Transient per-project save indicator. `saveActive` ticks this:
   *  idle → saving → saved (held 1500ms) → idle, or → error on failure.
   *  Surfaced in QuickLookHeader so the pill stays visible while the user
   *  scrolls the field list (the in-list label scrolls out of view). */
  saveStatus: Record<string, SaveStatus>
  /** Companion to `saveStatus === 'error'` — preserves the SaveError envelope
   *  so the in-list ErrorBanner can still render the error_code + message. */
  saveError: Record<string, SaveError | null>
  load: (projectId: string) => Promise<SchemaField[]>
  /** Direct human edit of the active prompt. Returns null on success
   *  or a SaveError envelope. On success, byProject is updated so the
   *  UI reflects the persisted state. */
  saveActive: (projectId: string, fields: SchemaField[], globalNotes?: string) => Promise<SaveError | null>
  invalidate: (projectId: string) => void
  reset: () => void
}

// Per-project saved→idle timers. Kept outside the store so callers can't
// accidentally serialize a number into JSON.
const savedTimers: Record<string, number> = {}

export const useSchema = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  saveStatus: {},
  saveError: {},
  reset: () => {
    Object.values(savedTimers).forEach((id) => window.clearTimeout(id))
    Object.keys(savedTimers).forEach((k) => delete savedTimers[k])
    set({ byProject: {}, loading: {}, saveStatus: {}, saveError: {} })
  },
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
    // Cancel any pending saved→idle tick from a previous save — the new save
    // takes precedence and will schedule its own tick on success.
    const pending = savedTimers[projectId]
    if (pending !== undefined) {
      window.clearTimeout(pending)
      delete savedTimers[projectId]
    }
    set((s) => ({
      saveStatus: { ...s.saveStatus, [projectId]: 'saving' },
      saveError: { ...s.saveError, [projectId]: null },
    }))
    const finish = (status: SaveStatus, err: SaveError | null) => {
      set((s) => ({
        saveStatus: { ...s.saveStatus, [projectId]: status },
        saveError: { ...s.saveError, [projectId]: err },
      }))
      if (status === 'saved') {
        savedTimers[projectId] = window.setTimeout(() => {
          delete savedTimers[projectId]
          set((s) => {
            // Only flip back to idle if we're still in 'saved' — a fresh save
            // may have moved us back to 'saving' / 'error' in the meantime.
            if (s.saveStatus[projectId] !== 'saved') return s
            return { saveStatus: { ...s.saveStatus, [projectId]: 'idle' } }
          })
        }, SAVED_HOLD_MS)
      }
    }
    // The PUT body overwrites both fields and notes server-side (no patch
    // semantics). When a caller passes only `fields` (e.g. SchemaFieldEditor),
    // we must carry forward the latest persisted notes — otherwise every
    // field edit silently clobbers global_notes to ''. NotesEditor / RawJsonTab
    // pass globalNotes explicitly and that wins.
    const effectiveNotes =
      globalNotes ?? usePrompts.getState().activeByProject[projectId]?.global_notes ?? ''
    try {
      const r = await fetch(`/lab/projects/${encodeURIComponent(projectId)}/prompts/active`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ schema: fields, global_notes: effectiveNotes }),
      })
      if (!r.ok) {
        let detail: SaveError = { error_code: `http_${r.status}` }
        try {
          const j = await r.json()
          detail = j?.detail ?? detail
        } catch { /* not json */ }
        finish('error', detail)
        return detail
      }
      const blob = await r.json() as { schema: SchemaField[] }
      const next = blob.schema ?? fields
      set((s) => ({ byProject: { ...s.byProject, [projectId]: next } }))
      // Keep usePrompts.activeByProject in lock-step: it's the source of
      // truth for RawJsonTab and any other consumer that derives off the
      // full ActivePrompt blob. Without this patch, form-side schema edits
      // (add/delete/rename/description) silently desync from raw json
      // until the project is re-loaded. NotesEditor + RawJsonTab.onSave
      // historically patched manually; centralising it here covers
      // SchemaFieldEditor too (and any future caller). Opportunistic: we
      // only touch entries already cached.
      usePrompts.setState((s) => {
        const cur = s.activeByProject[projectId]
        if (!cur) return s
        return {
          activeByProject: {
            ...s.activeByProject,
            [projectId]: {
              ...cur,
              schema: next,
              global_notes: effectiveNotes,
            },
          },
        }
      })
      finish('saved', null)
      return null
    } catch (e) {
      const err: SaveError = { error_code: 'network_error', error_message_en: (e as Error).message }
      finish('error', err)
      return err
    }
  },
}))
