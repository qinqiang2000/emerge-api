// frontend/src/stores/projects.ts
//
// Post-slug-transparency: the canonical project handle the frontend holds is
// `slug` — the human-readable on-disk folder name. `project_id` (`p_xxx`)
// remains in the Project shape only as an immutable internal anchor for chat
// events / job jsonl; UI code never selects by it.
import { create } from 'zustand'

import { listProjects, type Project } from '../lib/api'

interface State {
  projects: Project[]
  /** Currently selected project's slug — the URL/path-safe folder name. */
  selectedSlug: string | null
  loading: boolean
  refresh: () => Promise<void>
  select: (slug: string | null) => void
}

export const useProjects = create<State>((set) => ({
  projects: [],
  selectedSlug: null,
  loading: false,
  refresh: async () => {
    set({ loading: true })
    try {
      const ps = await listProjects()
      set({ projects: ps, loading: false })
    } catch {
      set({ loading: false })
    }
  },
  select: (slug) => set({ selectedSlug: slug }),
}))
