// frontend/src/stores/trash.ts — recycle bin contents + panel open state.
//
// Workspace-scoped (a deleted project lives here too), so unlike the other
// stores there is no per-project keying.
import { create } from 'zustand'

import { listTrash, restoreFromTrash, type TrashRow } from '../lib/api'

interface State {
  rows: TrashRow[]
  loading: boolean
  open: boolean
  /** Re-read the bin. Cheap and always fresh: called on mount and after every
   *  delete, so the sidebar entry appears the moment there's something in it
   *  and disappears once the bin drains. Swallows failures — an unreachable
   *  bin must never break the sidebar around it. */
  refresh: () => Promise<void>
  show: () => void
  hide: () => void
  /** Restore one entry and drop it from local state. Throws on refusal
   *  (occupied origin / vanished project) so the caller can surface why. */
  restore: (entry: string) => Promise<void>
}

export const useTrash = create<State>((set, get) => ({
  rows: [],
  loading: false,
  open: false,

  refresh: async () => {
    set({ loading: true })
    try {
      set({ rows: await listTrash(), loading: false })
    } catch {
      set({ loading: false })
    }
  },

  show: () => { set({ open: true }); void get().refresh() },
  hide: () => set({ open: false }),

  restore: async (entry) => {
    await restoreFromTrash(entry)
    set((s) => ({ rows: s.rows.filter((r) => r.entry !== entry) }))
  },
}))
