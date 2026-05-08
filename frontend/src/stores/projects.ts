// frontend/src/stores/projects.ts
import { create } from 'zustand'

import { listProjects, type Project } from '../lib/api'

interface State {
  projects: Project[]
  selectedId: string | null
  loading: boolean
  refresh: () => Promise<void>
  select: (id: string | null) => void
}

export const useProjects = create<State>((set) => ({
  projects: [],
  selectedId: null,
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
  select: (id) => set({ selectedId: id }),
}))
