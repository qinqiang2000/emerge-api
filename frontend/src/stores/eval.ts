import { create } from 'zustand'

import {
  getEvalCells,
  getEvalSummary,
  getLatestEval,
  listEvals,
  type EvalSnapshot,
} from '../lib/api'
import type {
  CellVerdict,
  EvalListEntry,
  ScoreResultSummary,
} from '../types/eval'

interface State {
  // null = fetched, no eval on disk yet; undefined = not fetched yet.
  byProject: Record<string, EvalSnapshot | null>
  loading: Record<string, boolean>
  load: (projectId: string) => Promise<EvalSnapshot | null>
  refresh: (projectId: string) => Promise<EvalSnapshot | null>
  invalidate: (projectId: string) => void
  reset: () => void

  // M12 — matrix page state.
  list: Record<string, EvalListEntry[]>
  summary: Record<string, ScoreResultSummary>
  cells: Record<string, CellVerdict[]>
  loadList: (slug: string) => Promise<void>
  loadSummary: (slug: string, ts: string) => Promise<void>
  loadCells: (slug: string, ts: string) => Promise<void>
}

async function fetchSlice(projectId: string): Promise<EvalSnapshot | null> {
  try {
    return await getLatestEval(projectId)
  } catch {
    return null
  }
}

export const useEval = create<State>((set, get) => ({
  byProject: {},
  loading: {},
  list: {},
  summary: {},
  cells: {},
  reset: () => set({
    byProject: {}, loading: {}, list: {}, summary: {}, cells: {},
  }),
  invalidate: (projectId) =>
    set((s) => {
      const next = { ...s.byProject }
      delete next[projectId]
      const nextList = { ...s.list }
      delete nextList[projectId]
      const nextSummary: Record<string, ScoreResultSummary> = {}
      const nextCells: Record<string, CellVerdict[]> = {}
      for (const k of Object.keys(s.summary)) {
        if (!k.startsWith(`${projectId}|`)) nextSummary[k] = s.summary[k]
      }
      for (const k of Object.keys(s.cells)) {
        if (!k.startsWith(`${projectId}|`)) nextCells[k] = s.cells[k]
      }
      return {
        byProject: next,
        list: nextList,
        summary: nextSummary,
        cells: nextCells,
      }
    }),
  load: async (projectId) => {
    if (projectId in get().byProject) return get().byProject[projectId]
    if (get().loading[projectId]) {
      return new Promise((resolve) => {
        const unsub = useEval.subscribe((s) => {
          if (projectId in s.byProject) {
            unsub()
            resolve(s.byProject[projectId])
          }
        })
      })
    }
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
  refresh: async (projectId) => {
    set((s) => ({ loading: { ...s.loading, [projectId]: true } }))
    const snap = await fetchSlice(projectId)
    set((s) => ({
      byProject: { ...s.byProject, [projectId]: snap },
      loading: { ...s.loading, [projectId]: false },
    }))
    return snap
  },
  async loadList(slug) {
    const rows = await listEvals(slug)
    set((s) => ({ list: { ...s.list, [slug]: rows } }))
  },
  async loadSummary(slug, ts) {
    const key = `${slug}|${ts}`
    if (get().summary[key]) return
    const snap = await getEvalSummary(slug, ts)
    if (snap == null) return
    set((s) => ({ summary: { ...s.summary, [key]: snap } }))
  },
  async loadCells(slug, ts) {
    const key = `${slug}|${ts}`
    if (get().cells[key]) return
    const rows = await getEvalCells(slug, ts)
    set((s) => ({ cells: { ...s.cells, [key]: rows } }))
  },
}))
