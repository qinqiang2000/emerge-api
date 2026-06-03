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
  /** True only while the user sits on a *fresh* new-project canvas (clicked
   *  the spine "新建项目" row), so EmptyHero can read as project-creation
   *  rather than a generic unbound scratch chat. Cleared the moment any
   *  project is selected. The project itself stays lazy — it materialises on
   *  disk once a doc is dropped / chat begins. */
  newProjectIntent: boolean
  loading: boolean
  refresh: () => Promise<void>
  select: (slug: string | null) => void
  /** Clear selection and arm new-project intent (spine "新建项目" row). */
  startNew: () => void
}

export const useProjects = create<State>((set) => ({
  projects: [],
  selectedSlug: null,
  newProjectIntent: false,
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
  select: (slug) => set({ selectedSlug: slug, newProjectIntent: false }),
  startNew: () => set({ selectedSlug: null, newProjectIntent: true }),
}))
