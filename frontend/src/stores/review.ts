// frontend/src/stores/review.ts
import { create } from 'zustand'

import { getExperimentPrediction, getPrediction, getReviewed, runExperimentPrediction, saveReviewed } from '../lib/api'
import type { ExperimentPredictionPayload, ReviewedPayload } from '../types/review'
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
  // ── experiment-tab state ─────────────────────────────────────────
  activeTabKey: 'active' | string  // 'active' or experiment_id
  predictionsByExp: Record<string, ExperimentPredictionPayload | null>
  // ── methods ──────────────────────────────────────────────────────
  open: (projectId: string, docId: string) => Promise<void>
  close: () => void
  setField: (entityIdx: number, name: string, value: unknown) => void
  setNote: (name: string, note: string) => void
  addEntity: () => void
  removeEntity: (idx: number) => void
  goPage: (page: number) => void
  setPageCount: (n: number) => void
  save: () => Promise<void>
  setActiveTab: (key: 'active' | string) => void
  loadExperimentPrediction: (experimentId: string) => Promise<void>
  runExperimentPrediction: (experimentId: string) => Promise<void>
  // ── adopt-from-prediction (label-studio-style) ───────────────────
  adoptPrediction: (
    entities: FieldsValue[],
    evidence?: Record<string, number | null>[] | null,
  ) => void
  adoptPredictionField: (
    entityIdx: number,
    name: string,
    value: unknown,
    evidencePage?: number | null,
  ) => void
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
  activeTabKey: 'active',
  predictionsByExp: {},
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
      activeTabKey: 'active',
      predictionsByExp: {},
    })
    try {
      // Fetch reviewed (user corrections) and prediction (latest extract) together.
      // Reviewed wins per-key when present; prediction backfills fields the user
      // never touched — including schema fields added after the doc was reviewed.
      const [reviewed, pred] = await Promise.all([
        getReviewed(projectId, docId),
        getPrediction(projectId, docId),
      ])
      const reviewedEnts = reviewed?.entities
      const predEnts = pred?.entities
      const base = reviewedEnts ?? predEnts ?? [{}]
      const entities = base.map((rev, i) => {
        const predEnt = (predEnts?.[i] ?? {}) as Record<string, unknown>
        const revEnt = (rev ?? {}) as Record<string, unknown>
        return reviewedEnts ? { ...predEnt, ...revEnt } : revEnt
      })
      set({
        entities,
        evidence: reviewed?._evidence ?? pred?._evidence ?? null,
        notes: reviewed?._notes ?? {},
        loading: false,
      })
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

  setActiveTab: (key) => set({ activeTabKey: key }),

  loadExperimentPrediction: async (experimentId) => {
    const { activeProjectId, activeDocId, predictionsByExp } = get()
    if (!activeProjectId || !activeDocId) return
    if (experimentId in predictionsByExp) return  // already attempted (success or 404)
    const payload = await getExperimentPrediction(activeProjectId, experimentId, activeDocId)
    set((s) => ({ predictionsByExp: { ...s.predictionsByExp, [experimentId]: payload } }))
  },

  runExperimentPrediction: async (experimentId) => {
    const { activeProjectId, activeDocId } = get()
    if (!activeProjectId || !activeDocId) return
    const payload = await runExperimentPrediction(activeProjectId, experimentId, activeDocId)
    set((s) => ({ predictionsByExp: { ...s.predictionsByExp, [experimentId]: payload } }))
  },

  adoptPrediction: (entities, evidence) => set({
    entities: entities.map((e) => ({ ...(e ?? {}) })),
    evidence: evidence ? evidence.map((e) => ({ ...(e ?? {}) })) : null,
    // Switch to the editable annotation tab so the user sees the result.
    activeTabKey: 'active',
  }),

  adoptPredictionField: (entityIdx, name, value, evidencePage) => set((s) => {
    const nextEntities = s.entities.slice()
    while (nextEntities.length <= entityIdx) nextEntities.push({})
    nextEntities[entityIdx] = { ...nextEntities[entityIdx], [name]: value }

    let nextEvidence = s.evidence
    if (evidencePage !== undefined) {
      const base = (s.evidence ?? []).slice() as Record<string, number | null>[]
      while (base.length <= entityIdx) base.push({})
      base[entityIdx] = { ...base[entityIdx], [name]: evidencePage }
      nextEvidence = base
    }
    return { entities: nextEntities, evidence: nextEvidence }
  }),
}))
