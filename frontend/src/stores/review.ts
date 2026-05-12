// frontend/src/stores/review.ts
import { create } from 'zustand'

import { getExperimentExtract, getPrediction, getReviewed, runExperimentExtract, saveReviewed } from '../lib/api'
import type { ExperimentExtractPayload, ReviewedPayload } from '../types/review'
import { useDocs } from './docs'

type FieldsValue = Record<string, unknown>

interface State {
  activeProjectId: string | null
  activeDocId: string | null
  page: number
  pageCount: number    // best-effort; defaulted to 1 until viewer probes
  loading: boolean
  saving: boolean
  err: string | null
  entities: FieldsValue[]
  evidence: Record<string, number | null>[] | null
  notes: Record<string, string>
  // ── M9.3 tab state ───────────────────────────────────────────────
  attachedExperimentIds: string[]
  activeTabKey: 'active' | string  // 'active' or experiment_id
  extractsByExp: Record<string, ExperimentExtractPayload | null>
  // ── existing methods ─────────────────────────────────────────────
  open: (projectId: string, docId: string) => Promise<void>
  close: () => void
  setField: (entityIdx: number, name: string, value: unknown) => void
  setNote: (name: string, note: string) => void
  addEntity: () => void
  removeEntity: (idx: number) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
  // ── M9.3 tab methods ─────────────────────────────────────────────
  attachExperiment: (experimentId: string) => Promise<void>
  detachExperiment: (experimentId: string) => void
  setActiveTab: (key: 'active' | string) => void
  loadExperimentExtract: (experimentId: string) => Promise<void>
  runExperimentExtract: (experimentId: string) => Promise<void>
}

export const useReview = create<State>((set, get) => ({
  activeProjectId: null,
  activeDocId: null,
  page: 1,
  pageCount: 1,
  loading: false,
  saving: false,
  err: null,
  entities: [],
  evidence: null,
  notes: {},
  attachedExperimentIds: [],
  activeTabKey: 'active',
  extractsByExp: {},
  open: async (projectId, docId) => {
    set({
      activeProjectId: projectId,
      activeDocId: docId,
      page: 1,
      pageCount: 1,
      loading: true,
      err: null,
      entities: [],
      evidence: null,
      notes: {},
      // ── tab state reset ──
      attachedExperimentIds: [],
      activeTabKey: 'active',
      extractsByExp: {},
    })
    try {
      // Prefer reviewed payload (resume a partial review); fall back to draft.
      const reviewed = await getReviewed(projectId, docId)
      if (reviewed) {
        set({
          entities: reviewed.entities ?? [],
          evidence: reviewed._evidence ?? null,
          notes: reviewed._notes ?? {},
          loading: false,
        })
        return
      }
      const pred = await getPrediction(projectId, docId)
      set({ entities: pred?.entities ?? [{}], evidence: pred?._evidence ?? null, notes: {}, loading: false })
    } catch (e: unknown) {
      set({ err: String(e), loading: false })
    }
  },
  close: () => set({ activeProjectId: null, activeDocId: null, entities: [], evidence: null, notes: {}, page: 1 }),
  setField: (entityIdx, name, value) => set((s) => {
    const next = s.entities.slice()
    const cur = next[entityIdx] ?? {}
    next[entityIdx] = { ...cur, [name]: value }
    return { entities: next }
  }),
  setNote: (name, note) => set((s) => ({ notes: { ...s.notes, [name]: note } })),
  addEntity: () => set((s) => ({ entities: [...s.entities, {}] })),
  removeEntity: (idx) => set((s) => ({
    entities: s.entities.length > 1 ? s.entities.filter((_, i) => i !== idx) : s.entities,
  })),
  goPage: (page) => set((s) => ({ page: Math.max(1, Math.min(s.pageCount, page)) })),
  setPageCount: (n) => set({ pageCount: Math.max(1, n) }),
  save: async () => {
    const { activeProjectId, activeDocId, entities, evidence, notes } = get()
    if (!activeProjectId || !activeDocId) return
    set({ saving: true, err: null })
    try {
      const payload: ReviewedPayload = {
        entities,
        source: 'manual',
        ...(evidence ? { _evidence: evidence } : {}),
        ...(Object.keys(notes).length > 0 ? { _notes: notes } : {}),
      }
      await saveReviewed(activeProjectId, activeDocId, payload)
      // refresh the doc-list status so the badge flips to "reviewed"
      void useDocs.getState().refresh(activeProjectId)
      set({ saving: false })
    } catch (e: unknown) {
      set({ err: String(e), saving: false })
    }
  },

  attachExperiment: async (experimentId) => {
    const { attachedExperimentIds } = get()
    if (attachedExperimentIds.includes(experimentId)) return
    set((s) => ({ attachedExperimentIds: [...s.attachedExperimentIds, experimentId] }))
    await get().loadExperimentExtract(experimentId)
  },

  detachExperiment: (experimentId) => {
    set((s) => ({
      attachedExperimentIds: s.attachedExperimentIds.filter((x) => x !== experimentId),
      activeTabKey: s.activeTabKey === experimentId ? 'active' : s.activeTabKey,
    }))
  },

  setActiveTab: (key) => set({ activeTabKey: key }),

  loadExperimentExtract: async (experimentId) => {
    const { activeProjectId, activeDocId, extractsByExp } = get()
    if (!activeProjectId || !activeDocId) return
    if (experimentId in extractsByExp) return  // already attempted (success or 404)
    const payload = await getExperimentExtract(activeProjectId, experimentId, activeDocId)
    set((s) => ({ extractsByExp: { ...s.extractsByExp, [experimentId]: payload } }))
  },

  runExperimentExtract: async (experimentId) => {
    const { activeProjectId, activeDocId } = get()
    if (!activeProjectId || !activeDocId) return
    const payload = await runExperimentExtract(activeProjectId, experimentId, activeDocId)
    set((s) => ({ extractsByExp: { ...s.extractsByExp, [experimentId]: payload } }))
  },
}))
